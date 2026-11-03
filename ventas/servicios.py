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
from .pagos_calculos import leer_tipos_pago, preparar_pagos, validar_pagos_guardados


def _validar_linea_factura(documento, linea):
    servicio = linea.servicio
    if (not servicio.activo or not linea.barbero_id or not linea.descripcion_barbero
        or linea.cantidad_servicio <= 0 or linea.linea_original_id is not None
        or linea.retencion_impuesto is None
        or linea.retencion_impuesto != servicio.retencion_impuesto
        or linea.impuesto_normal != (not linea.retencion_impuesto)):
        raise ValidationError("Los datos del servicio o su impuesto son inválidos.")
    manual = servicio.modo_precio == 'manual'
    if (linea.precio_manual != manual or linea.precio_unitario_usd < 0
        or (manual and linea.precio_unitario_usd <= 0)
        or (not manual and linea.precio_unitario_usd != servicio.precio)):
        raise ValidationError("El precio del servicio no es válido.")
    calculado = calcular_linea_segun_retencion(
        linea.precio_unitario_usd, linea.cantidad_servicio,
        Decimal(str(documento.tasa_bcv)), Decimal(str(documento.impuesto)),
        Decimal(str(documento.descuento_porcentaje)), linea.retencion_impuesto)
    if any(getattr(linea, campo) != valor for campo, valor in calculado.items()):
        raise ValidationError("El precio, descuento o impuesto del servicio no coincide.")


def _validar_linea_reverso(documento, linea):
    original = documento.documento_original
    anterior = linea.linea_original
    iguales = ('servicio_id', 'barbero_id', 'descripcion_barbero', 'codigo_servicio',
               'descripcion_servicio', 'cantidad_servicio', 'precio_manual',
               'retencion_impuesto', 'impuesto_normal')
    negativos = ('precio_unitario_usd', 'monto_servicio', 'monto_servicio_bs',
                 'monto_impuesto', 'monto_descuento_usd', 'monto_descuento_bs')
    if (not original or not anterior or anterior.documento_id != original.pk
        or any(getattr(linea, c) != getattr(anterior, c) for c in iguales)
        or any(getattr(linea, c) != -getattr(anterior, c) for c in negativos)):
        raise ValidationError("Los servicios del reverso no coinciden con la factura original.")
    for campo in ('base_imponible_usd', 'base_imponible_bs'):
        base_anterior = getattr(anterior, campo)
        esperada = -base_anterior if base_anterior is not None else None
        if getattr(linea, campo) != esperada:
            raise ValidationError("Las bases del reverso no coinciden con la factura original.")


def _validar_pago_venta(documento, pago):
    if pago.tipo_pago <= 0 or pago.moneda not in ('USD', 'BS') or not pago.nombre_tipo_pago:
        raise ValidationError("La forma de pago de la factura es inválida.")
    convertido = dinero(Decimal(str(pago.monto)) * Decimal(str(documento.tasa_bcv))) if pago.moneda == 'USD' else pago.monto
    if pago.equivalente_bs != convertido:
        raise ValidationError("El equivalente del pago no coincide con la tasa.")
    if documento.tipo_documento == 'FA':
        if pago.monto <= 0 or pago.pago_original_id is not None:
            raise ValidationError("El pago de la factura es inválido.")
    elif documento.tipo_documento == 'RE':
        anterior = pago.pago_original
        if not anterior or anterior.documento_id != documento.documento_original_id:
            raise ValidationError("El pago del reverso no pertenece a la factura original.")
        iguales = ('tipo_pago','moneda','nombre_tipo_pago','fecha','referencia','observacion')
        negativos = ('monto','equivalente_bs','ajuste_redondeo_bs')
        if (pago.monto >= 0 or any(getattr(pago,c) != getattr(anterior,c) for c in iguales)
            or any(getattr(pago,c) != -getattr(anterior,c) for c in negativos)):
            raise ValidationError("El pago del reverso no coincide con el original.")
    else:
        raise ValidationError("El tipo de documento es inválido.")


def _validar_sello(documento):
    """Comprueba las sumas persistidas antes de finalizar el documento."""
    detalles = list(documento.detalles.all())
    pagos = list(documento.pagos.all())
    if not detalles:
        raise ValidationError("La factura necesita al menos un servicio.")
    cero = Decimal("0.00")
    if documento.iva_incluido:
        if any(d.base_imponible_usd is None or d.base_imponible_bs is None for d in detalles):
            raise ValidationError("Falta la base imponible de un servicio.")
        base_usd = sum((d.base_imponible_usd for d in detalles), cero)
        base_bs = sum((d.base_imponible_bs for d in detalles), cero)
    else:
        base_usd = sum((d.monto_servicio - d.monto_descuento_usd for d in detalles), cero)
        base_bs = sum((d.monto_servicio_bs - d.monto_descuento_bs for d in detalles), cero)
    if documento.tipo_documento == "FA":
        if documento.documento_original_id is not None or not documento.iva_incluido:
            raise ValidationError("La factura de servicios es inválida.")
        for linea in detalles:
            _validar_linea_factura(documento, linea)
        if any(p.monto <= 0 or p.pago_original_id is not None for p in pagos):
            raise ValidationError("El pago de la factura es inválido.")
        try:
            validar_pagos_guardados(pagos, documento.total_bs, documento.tasa_bcv)
        except ValueError as error:
            raise ValidationError(str(error)) from error
    elif documento.tipo_documento != "RE":
        raise ValidationError("El tipo de documento es inválido.")
    for pago in pagos:
        _validar_pago_venta(documento, pago)
    esperados = (
        (documento.subtotal_usd, base_usd),
        (documento.subtotal_bs, base_bs),
        (documento.total_impuesto_bs, sum((d.monto_impuesto for d in detalles), cero)),
        (documento.descuento_usd, sum((d.monto_descuento_usd for d in detalles), cero)),
        (documento.descuento_bs, sum((d.monto_descuento_bs for d in detalles), cero)),
        (documento.total_bs, documento.subtotal_bs + documento.total_impuesto_bs),
        (documento.total_bs, sum((p.equivalente_bs + p.ajuste_redondeo_bs for p in pagos), cero)),
    )
    if any(actual != esperado for actual, esperado in esperados):
        raise ValidationError("Los detalles, descuentos o pagos no coinciden con el total de la factura.")
    if documento.total_bs and not pagos:
        raise ValidationError("La factura necesita pagos.")
    if documento.tipo_documento == "RE":
        original = documento.documento_original
        if not original or not original.sellado:
            raise ValidationError("El reverso necesita una factura original registrada.")
        if len(detalles) != original.detalles.count() or len(pagos) != original.pagos.count():
            raise ValidationError("El reverso debe contener todos los servicios y pagos originales.")
        campos_iguales = ('cliente_id', 'tasa_bcv', 'impuesto', 'iva_incluido', 'descuento_porcentaje')
        campos_negativos = ('subtotal_usd', 'subtotal_bs', 'total_impuesto_bs', 'total_bs', 'descuento_usd', 'descuento_bs')
        if (original.tipo_documento != 'FA' or not documento.motivo_reverso.strip()
            or any(getattr(documento, c) != getattr(original, c) for c in campos_iguales)
            or any(getattr(documento, c) != -getattr(original, c) for c in campos_negativos)):
            raise ValidationError("El reverso no coincide con la factura original.")
        for linea in detalles:
            _validar_linea_reverso(documento, linea)
        for pago in pagos:
            anterior = pago.pago_original
            iguales = ('tipo_pago', 'moneda', 'nombre_tipo_pago', 'fecha', 'referencia', 'observacion')
            negativos = ('monto', 'equivalente_bs', 'ajuste_redondeo_bs')
            if (not anterior or anterior.documento_id != original.pk
                or any(getattr(pago,c) != getattr(anterior,c) for c in iguales)
                or any(getattr(pago,c) != -getattr(anterior,c) for c in negativos)):
                raise ValidationError("Los pagos del reverso no coinciden con la factura original.")


def _sellar(documento):
    _validar_sello(documento)
    with connection.cursor() as cursor:
        cursor.execute('UPDATE ventas_documentoventa SET sellado = %s WHERE id_documento = %s AND sellado = %s', [True, documento.pk, False])
        if cursor.rowcount != 1:
            raise ValidationError('La factura ya fue finalizada o no existe.')
    documento.sellado = True


@transaction.atomic
def registrar_venta(*, fecha, cliente, lineas, pagos, clave, usuario, aplicar_descuento=False, descuento_porcentaje=Decimal("50.00")):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    existente = DocumentoVenta.objects.filter(clave_operacion=clave, sellado=True).first()
    if existente:
        return existente
    from django.apps import apps
    if apps.is_installed("control_inventario"):
        from control_inventario.servicios import validar_fecha
        validar_fecha(fecha)
    cliente = Cliente.objects.get(pk=cliente.pk, activo=True)
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        raise ValidationError("No hay tasa Bs registrada para esa fecha. Regístrala antes de guardar.")
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
    creados = []
    for datos_pago in pagos_preparados:
        creados.append(PagoVenta.objects.create(documento=documento, **datos_pago))
    _sellar(documento)
    from bancos.vinculacion import vincular_pagos_nuevos
    vincular_pagos_nuevos(usuario, 'SERVICIOS', pagos, creados)
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
    from bancos.vinculacion import reflejar_reversos_venta
    reflejar_reversos_venta('SERVICIOS', reverso.pagos.all())
    return reverso
