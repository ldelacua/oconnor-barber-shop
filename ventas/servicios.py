from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from tasas_bcv.models import TasaBCV
from .calculos import leer_impuesto, calcular_linea
from .models import DocumentoVenta, DetalleVenta, PagoVenta
from .pagos_calculos import leer_tipos_pago, preparar_pagos


def _sellar(documento):
    with connection.cursor() as cursor:
        cursor.execute('UPDATE ventas_documentoventa SET sellado = %s WHERE id_documento = %s AND sellado = %s', [True, documento.pk, False])
    documento.sellado = True


@transaction.atomic
def registrar_venta(*, fecha, cliente, lineas, pagos, clave, usuario):
    existente = DocumentoVenta.objects.filter(clave_operacion=clave, sellado=True).first()
    if existente:
        return existente
    cliente = Cliente.objects.get(pk=cliente.pk, activo=True)
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if not tasa:
        raise ValidationError("No hay tasa BCV registrada para esa fecha. Regístrala antes de guardar.")
    impuesto = leer_impuesto()
    preparadas = []
    for linea in lineas:
        servicio = Servicio.objects.get(pk=linea["servicio"].pk, activo=True)
        barbero = Barbero.objects.get(pk=linea["barbero"].pk, activo=True)
        if servicio.precio < 0:
            raise ValidationError("Un servicio tiene un precio negativo. Corrígelo antes de vender.")
        importes = calcular_linea(servicio.precio, linea["cantidad_servicio"], tasa.tasa_bcv, impuesto)
        preparadas.append({
            "barbero": barbero, "descripcion_barbero": f"{barbero.nombre} {barbero.apellido}",
            "servicio": servicio, "codigo_servicio": servicio.codigo,
            "descripcion_servicio": servicio.nombre,
            "cantidad_servicio": linea["cantidad_servicio"],
            "precio_unitario_usd": servicio.precio, **importes,
        })
    if not preparadas:
        raise ValidationError("Añade al menos un servicio.")
    totales = {
        nombre: sum((p[campo] for p in preparadas), Decimal("0.00"))
        for nombre, campo in [("subtotal_usd", "monto_servicio"), ("subtotal_bs", "monto_servicio_bs"), ("total_impuesto_bs", "monto_impuesto")]
    }
    importes_totales = list(totales.values()) + [totales["subtotal_bs"] + totales["total_impuesto_bs"]]
    if any(abs(valor) >= Decimal("10000000000000000") for valor in importes_totales):
        raise ValidationError("El importe supera la capacidad del documento. Revisa la tasa y las cantidades.")
    try:
        pagos_preparados = preparar_pagos(
            pagos, totales["subtotal_bs"] + totales["total_impuesto_bs"],
            tasa.tasa_bcv, leer_tipos_pago(),
        )
    except (ValueError, KeyError, OSError, ArithmeticError) as error:
        raise ValidationError(str(error)) from error
    documento = DocumentoVenta.objects.create(
        tipo_documento="FA", fecha=fecha, cliente=cliente,
        tasa_bcv=tasa.tasa_bcv, impuesto=impuesto, clave_operacion=clave,
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
    original = DocumentoVenta.objects.get(pk=documento_id, sellado=True)
    if original.tipo_documento != "FA":
        raise ValidationError("Solo se puede reversar una FA.")
    if DocumentoVenta.objects.filter(documento_original=original).exists():
        raise ValidationError("Esta FA ya tiene un reverso registrado.")
    reverso = DocumentoVenta.objects.create(
        tipo_documento="RE", fecha=timezone.localdate(), cliente_id=original.cliente_id,
        tasa_bcv=original.tasa_bcv, impuesto=original.impuesto,
        documento_original=original, motivo_reverso=motivo,
        subtotal_usd=-original.subtotal_usd, subtotal_bs=-original.subtotal_bs,
        total_impuesto_bs=-original.total_impuesto_bs, total_bs=-original.total_bs,
        registrado_por=usuario.get_username(),
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
