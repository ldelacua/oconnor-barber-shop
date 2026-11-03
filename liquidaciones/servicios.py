from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from barberos.models import Barbero
from tasas_bcv.models import TasaBCV
from ventas.calculos import dinero
from ventas.models import DetalleVenta
from ventas.pagos_calculos import leer_tipos_pago, validar_pagos_guardados
from .models import Liquidacion, DetalleLiquidacion, PagoLiquidacion
from .pagos import preparar_pagos


def comision(base, porcentaje):
    with localcontext() as contexto:
        contexto.prec = 60
        return dinero(base * porcentaje / Decimal("100"))


def pendientes(prestador, desde, hasta, fecha):
    porcentaje = prestador.porcentaje
    if not Decimal("0") <= porcentaje <= Decimal("100"):
        raise ValidationError("El porcentaje del prestador debe estar entre 0 y 100.")
    lineas = DetalleVenta.objects.filter(
        barbero=prestador, documento__sellado=True, documento__tipo_documento="FA",
        documento__reverso__isnull=True, documento__fecha__range=(desde, hasta),
        comision_liquidada__isnull=True,
    ).select_related("documento").order_by("documento__fecha", "pk")
    # monto_servicio conserva el precio original (IVA incluido cuando corresponde),
    # antes del descuento. Nunca usar base_imponible_usd para la comisión.
    servicios = [{"linea": l, "porcentaje": porcentaje, "base": l.monto_servicio,
                  "comision": comision(l.monto_servicio, porcentaje), "ajuste_de": None} for l in lineas]
    pagadas = DetalleLiquidacion.objects.filter(
        liquidacion__prestador=prestador, liquidacion__sellado=True,
        detalle_venta__documento__tipo_documento="FA", descuento__isnull=True,
        detalle_venta__documento__reverso__sellado=True,
        detalle_venta__documento__reverso__fecha__lte=fecha,
    ).select_related("detalle_venta__documento__reverso")
    # Cada RE conserva el orden y los datos de las líneas originales. Se
    # comprueba la correspondencia antes de crear un descuento.
    mapas = {}
    descuentos = []
    for pagada in pagadas:
        original = pagada.detalle_venta.documento
        if original.pk not in mapas:
            fa = list(original.detalles.order_by("pk"))
            re = list(original.reverso.detalles.order_by("pk"))
            if len(fa) != len(re):
                raise ValidationError(f"No se pueden relacionar las líneas de {original} y su RE.")
            mapa = {}
            for a, b in zip(fa, re):
                if (a.servicio_id != b.servicio_id or a.barbero_id != b.barbero_id
                    or a.cantidad_servicio != b.cantidad_servicio
                    or a.monto_servicio != -b.monto_servicio):
                    raise ValidationError(f"Las líneas del reverso de {original} no coinciden.")
                mapa[a.pk] = b
            mapas[original.pk] = mapa
        reversada = mapas[original.pk][pagada.detalle_venta_id]
        descuentos.append({"linea": reversada, "porcentaje": pagada.porcentaje,
                           "base": -pagada.monto_servicio_usd,
                           "comision": -pagada.comision_usd, "ajuste_de": pagada})
    return servicios, descuentos


@transaction.atomic
def registrar(*, prestador_id, desde, hasta, fecha, seleccion, pagos, clave, usuario, incluir_productos=False):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    existente = Liquidacion.objects.filter(clave=clave, sellado=True).first()
    if existente:
        return existente
    if desde > hasta or hasta > fecha:
        raise ValidationError("Revisa el período y la fecha de cancelación.")
    prestador = Barbero.objects.get(pk=prestador_id)
    servicios, descuentos = pendientes(prestador, desde, hasta, fecha)
    ids = set(seleccion)
    candidatas = {s["linea"].pk: s for s in servicios}
    if not ids.issubset(candidatas):
        raise ValidationError("Selecciona servicios pendientes válidos. Alguno puede haberse pagado o reversado; vuelve a consultar.")
    elegidas = [candidatas[id_] for id_ in sorted(ids)] + descuentos
    from .comisiones_productos import pendientes_productos, reintegros_pendientes
    productos = pendientes_productos(prestador, desde, hasta, fecha) if incluir_productos else None
    reintegros = reintegros_pendientes(prestador, fecha)
    if not ids and not (productos and productos['ventas']):
        raise ValidationError('Selecciona servicios o incluye ventas de productos pendientes.')
    total_productos = productos['resumen']['comision_usd'] if productos else Decimal('0.00')
    total_reintegros = -sum((r.comision_usd for r in reintegros), Decimal('0.00'))
    total = sum((s["comision"] for s in elegidas), Decimal("0.00")) + total_productos + total_reintegros
    if total <= 0:
        raise ValidationError("Los descuentos dejan un saldo cero o negativo. Quedan pendientes para una próxima liquidación con saldo a pagar.")
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        raise ValidationError("Registra la tasa Bs de la fecha de cancelación antes de pagar.")
    with localcontext() as contexto:
        contexto.prec = 60
        total_bs = dinero(total * tasa.tasa_bcv)
    if total >= Decimal("10000000000000000") or total_bs >= Decimal("10000000000000000"):
        raise ValidationError("La liquidación supera el límite de importes.")
    try:
        preparados = preparar_pagos(pagos, total_bs, tasa.tasa_bcv, leer_tipos_pago(), total_usd_objetivo=total)
    except (ValueError, KeyError, OSError, ArithmeticError) as error:
        raise ValidationError(str(error)) from error
    liquidacion = Liquidacion.objects.create(
        prestador=prestador, nombre_prestador=f"{prestador.nombre} {prestador.apellido}",
        periodo_desde=desde, periodo_hasta=hasta, fecha_cancelacion=fecha,
        tasa_bcv=tasa.tasa_bcv, total_comision_usd=total, total_bs=total_bs,
        total_servicios_usd=sum((s["base"] for s in elegidas), Decimal("0.00")),
        registrado_por=usuario.get_username(), clave=clave,
    )
    for s in elegidas:
        DetalleLiquidacion.objects.create(
            liquidacion=liquidacion, detalle_venta=s["linea"], ajuste_de=s["ajuste_de"],
            porcentaje=s["porcentaje"], monto_servicio_usd=s["base"], comision_usd=s["comision"],
        )
    from .models import PeriodoComisionProductos, ComisionVentaProducto, ReintegroComisionProducto
    if productos and productos['ventas']:
        resumen = productos['resumen']
        periodo = PeriodoComisionProductos.objects.create(
            liquidacion=liquidacion, prestador=prestador, desde=desde, hasta=hasta,
            unidades=resumen['unidades'], base_usd=resumen['base_usd'],
            porcentaje=resumen['porcentaje'], comision_usd=resumen['comision_usd'])
        for linea in productos['ventas']:
            ComisionVentaProducto.objects.create(periodo=periodo, **linea)
    for anterior in reintegros:
        ReintegroComisionProducto.objects.create(liquidacion=liquidacion, comision=anterior,
            reverso=anterior.venta.reverso, monto_usd=-anterior.comision_usd)
    creados = []
    for p in preparados:
        creados.append(PagoLiquidacion.objects.create(liquidacion=liquidacion, **p))
    detalles_guardados = list(liquidacion.detalles.all())
    pagos_guardados = list(liquidacion.pagos.all())
    cero = Decimal("0.00")
    if productos and productos['ventas']:
        ventas_guardadas = list(periodo.ventas.all())
        if (sum((v.unidades for v in ventas_guardadas), cero) != periodo.unidades
                or sum((v.base_usd for v in ventas_guardadas), cero) != periodo.base_usd
                or sum((v.comision_usd for v in ventas_guardadas), cero) != periodo.comision_usd
                or {v.venta_id for v in ventas_guardadas} != {v['venta'].pk for v in productos['ventas']}):
            raise ValidationError('Las ventas de productos no coinciden con la comisión del período.')
    reintegros_guardados = list(liquidacion.reintegros_productos.all())
    if ({r.comision_id for r in reintegros_guardados} != {r.pk for r in reintegros}
            or sum((r.monto_usd for r in reintegros_guardados), cero) != total_reintegros):
        raise ValidationError('Los reintegros de productos no coinciden con los reversos pendientes.')
    if (not detalles_guardados and not (productos and productos['ventas'])) or not pagos_guardados:
        raise ValidationError("La liquidación necesita servicios y pagos.")
    if not any(d.ajuste_de_id is None for d in detalles_guardados) and not (productos and productos['ventas']):
        raise ValidationError("La liquidación necesita servicios originales.")
    try:
        validar_pagos_guardados(pagos_guardados, liquidacion.total_bs, liquidacion.tasa_bcv,
                               total_usd_objetivo=liquidacion.total_comision_usd)
    except ValueError as error:
        raise ValidationError(str(error)) from error
    if (liquidacion.total_servicios_usd != sum((d.monto_servicio_usd for d in detalles_guardados), cero)
        or liquidacion.total_comision_usd != sum((d.comision_usd for d in detalles_guardados), cero) + total_productos + total_reintegros
        or liquidacion.total_bs != dinero(liquidacion.total_comision_usd * liquidacion.tasa_bcv)
        or liquidacion.total_bs != sum((p.equivalente_bs + p.ajuste_redondeo_bs for p in pagos_guardados), cero)):
        raise ValidationError("Los servicios o pagos no coinciden con el total de la liquidación.")
    with connection.cursor() as cursor:
        cursor.execute('UPDATE liquidaciones_liquidacion SET sellado=%s WHERE id_cancelacion=%s AND sellado=%s', [True, liquidacion.pk, False])
        if cursor.rowcount != 1:
            raise ValidationError('La liquidación ya fue finalizada o no existe.')
    liquidacion.sellado = True
    from bancos.vinculacion import vincular_pagos_nuevos
    vincular_pagos_nuevos(usuario, 'PRESTADOR', pagos, creados)
    return liquidacion
