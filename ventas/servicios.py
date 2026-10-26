from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from tasas_bcv.models import TasaBCV
from .calculos import leer_impuesto, calcular_linea_segun_retencion, dinero
from .models import DocumentoVenta, DetalleVenta, PagoVenta
from .pagos_calculos import leer_tipos_pago, preparar_pagos


def _sellar(documento):
    with connection.cursor() as cursor:
        cursor.execute('UPDATE ventas_documentoventa SET sellado = %s WHERE id_documento = %s AND sellado = %s', [True, documento.pk, False])
    documento.sellado = True


@transaction.atomic
def registrar_venta(*, fecha, cliente, lineas, pagos, clave, usuario, aplicar_descuento=False, descuento_porcentaje=Decimal("50.00")):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    existente = DocumentoVenta.objects.filter(clave_operacion=clave, sellado=True).first()
    if existente:
        return existente
    cliente = Cliente.objects.get(pk=cliente.pk, activo=True)
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        raise ValidationError("No hay tasa BCV registrada para esa fecha. Regístrala antes de guardar.")
    impuesto = leer_impuesto()
    try:
        descuento = Decimal(str(descuento_porcentaje)) if aplicar_descuento else Decimal("0.00")
        if not descuento.is_finite() or not Decimal("0") <= descuento <= Decimal("100") or dinero(descuento) != descuento:
            raise ValueError()
        if aplicar_descuento and descuento <= 0:
            raise ValueError()
    except (ValueError, ArithmeticError):
        raise ValidationError("El descuento debe estar entre 0.01 y 100, con dos decimales como máximo.")
    preparadas = []
    for linea in lineas:
        servicio = Servicio.objects.get(pk=linea["servicio"].pk, activo=True)
        barbero = Barbero.objects.get(pk=linea["barbero"].pk, activo=True)
        if servicio.precio < 0:
            raise ValidationError("Un servicio tiene un precio negativo. Corrígelo antes de vender.")
        precio = servicio.precio
        manual = servicio.modo_precio == "manual"
        if manual:
            try:
                precio = Decimal(str(linea.get("precio_unitario_usd")))
                if not precio.is_finite() or precio <= 0 or dinero(precio) != precio:
                    raise ValueError()
            except (ValueError, ArithmeticError):
                raise ValidationError(f"Introduce un precio manual positivo de hasta dos decimales para {servicio.nombre}.")
        cantidad = linea["cantidad_servicio"]
        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or not 1 <= cantidad <= 10000:
            raise ValidationError("La cantidad debe estar entre 1 y 10000.")
        importes = calcular_linea_segun_retencion(precio, cantidad, tasa.tasa_bcv, impuesto, descuento, servicio.retencion_impuesto)
        preparadas.append({
            "barbero": barbero, "descripcion_barbero": f"{barbero.nombre} {barbero.apellido}",
            "servicio": servicio, "codigo_servicio": servicio.codigo,
            "descripcion_servicio": servicio.nombre,
            "cantidad_servicio": linea["cantidad_servicio"],
            "precio_unitario_usd": precio, "precio_manual": manual, "retencion_impuesto": servicio.retencion_impuesto, "impuesto_normal": not servicio.retencion_impuesto, **importes,
        })
    if not preparadas:
        raise ValidationError("Añade al menos un servicio.")
    totales = {
        nombre: sum((p[campo] for p in preparadas), Decimal("0.00"))
        for nombre, campo in [("subtotal_usd", "base_imponible_usd"), ("subtotal_bs", "base_imponible_bs"), ("total_impuesto_bs", "monto_impuesto")]
    }
    totales["descuento_usd"] = sum((p["monto_descuento_usd"] for p in preparadas), Decimal("0.00"))
    totales["descuento_bs"] = sum((p["monto_descuento_bs"] for p in preparadas), Decimal("0.00"))
    importes_totales = [p[c] for p in preparadas for c in ("monto_servicio", "monto_servicio_bs", "precio_unitario_usd")] + list(totales.values()) + [totales["subtotal_bs"] + totales["total_impuesto_bs"]]
    if any(abs(valor) >= Decimal("10000000000000000") for valor in importes_totales):
        raise ValidationError("El importe supera la capacidad del documento. Revisa la tasa y las cantidades.")
    try:
        total_bs = totales["subtotal_bs"] + totales["total_impuesto_bs"]
        if total_bs == 0:
            if pagos:
                raise ValueError("El total es cero: no registres pagos para este documento.")
            pagos_preparados = []
        else:
            pagos_preparados = preparar_pagos(pagos, total_bs, tasa.tasa_bcv, leer_tipos_pago())
    except (ValueError, KeyError, OSError, ArithmeticError) as error:
        raise ValidationError(str(error)) from error
    documento = DocumentoVenta.objects.create(
        tipo_documento="FA", fecha=fecha, cliente=cliente, iva_incluido=True,
        tasa_bcv=tasa.tasa_bcv, impuesto=impuesto, clave_operacion=clave,
        descuento_porcentaje=descuento,
        registrado_por=usuario.get_username(), **totales,
        total_bs=totales["subtotal_bs"] + totales["total_impuesto_bs"],
    )
    for datos in preparadas:
        DetalleVenta.objects.create(documento=documento, **datos)
    for datos_pago in pagos_preparados:
        PagoVenta.objects.create(documento=documento, **datos_pago)
    _sellar(documento)
    return documento


@transaction.atomic
def registrar_reverso(*, documento_id, motivo, usuario):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    original = DocumentoVenta.objects.get(pk=documento_id, sellado=True)
    if original.tipo_documento != "FA":
        raise ValidationError("Solo se puede reversar una FA.")
    if DocumentoVenta.objects.filter(documento_original=original).exists():
        raise ValidationError("Esta FA ya tiene un reverso registrado.")
    reverso = DocumentoVenta.objects.create(
        tipo_documento="RE", fecha=timezone.localdate(), cliente_id=original.cliente_id,
        tasa_bcv=original.tasa_bcv, impuesto=original.impuesto, iva_incluido=original.iva_incluido,
        documento_original=original, motivo_reverso=motivo,
        subtotal_usd=-original.subtotal_usd, subtotal_bs=-original.subtotal_bs,
        total_impuesto_bs=-original.total_impuesto_bs, total_bs=-original.total_bs,
        registrado_por=usuario.get_username(),
        descuento_porcentaje=original.descuento_porcentaje,
        descuento_usd=-original.descuento_usd, descuento_bs=-original.descuento_bs,
    )
    for linea in original.detalles.all():
        DetalleVenta.objects.create(
            documento=reverso, servicio_id=linea.servicio_id,
            barbero_id=linea.barbero_id, descripcion_barbero=linea.descripcion_barbero,
            codigo_servicio=linea.codigo_servicio, descripcion_servicio=linea.descripcion_servicio,
            cantidad_servicio=linea.cantidad_servicio,
            precio_unitario_usd=-linea.precio_unitario_usd,
            monto_servicio=-linea.monto_servicio,
            monto_servicio_bs=-linea.monto_servicio_bs,
            monto_impuesto=-linea.monto_impuesto,
            retencion_impuesto=linea.retencion_impuesto,
            impuesto_normal=linea.impuesto_normal,
            base_imponible_usd=-linea.base_imponible_usd if linea.base_imponible_usd is not None else None,
            base_imponible_bs=-linea.base_imponible_bs if linea.base_imponible_bs is not None else None,
            precio_manual=linea.precio_manual, linea_original=linea,
            monto_descuento_usd=-linea.monto_descuento_usd,
            monto_descuento_bs=-linea.monto_descuento_bs,
        )
    for pago in original.pagos.all():
        PagoVenta.objects.create(
            documento=reverso, tipo_pago=pago.tipo_pago,
            nombre_tipo_pago=pago.nombre_tipo_pago, moneda=pago.moneda,
            fecha=pago.fecha, referencia=pago.referencia, observacion=pago.observacion,
            monto=-pago.monto, equivalente_bs=-pago.equivalente_bs,
            ajuste_redondeo_bs=-pago.ajuste_redondeo_bs, pago_original=pago,
        )
    _sellar(reverso)
    return reverso
