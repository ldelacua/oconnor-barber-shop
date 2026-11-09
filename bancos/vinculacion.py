from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import CierreBancario, CuentaBancaria, MovimientoInterno


def fuentes():
    from ventas.models import PagoVenta
    from ventas_productos.models import PagoProducto
    from liquidaciones.models import PagoLiquidacion
    from inventario.models import PagoProveedor
    return {
        'SERVICIOS': (PagoVenta.objects.filter(documento__sellado=True, documento__cobro_compartido__isnull=True), 1),
        'PRODUCTOS': (PagoProducto.objects.filter(documento__sellado=True, documento__cobro_compartido__isnull=True), 1),
        'PRESTADOR': (PagoLiquidacion.objects.filter(liquidacion__sellado=True), -1),
        'PROVEEDOR': (PagoProveedor.objects.filter(reverso__isnull=True), -1),
    }


@transaction.atomic
def vincular(usuario, cuenta, origen, pago_id):
    if not usuario.has_perm('bancos.add_movimientointerno'):
        raise PermissionDenied
    if origen == 'PROVEEDOR':
        from mysql_nuevo.bloqueos import serializar_operacion
        serializar_operacion()
    consulta, signo = fuentes()[origen]
    modelo = consulta.model._meta
    if not usuario.has_perm(f'{modelo.app_label}.view_{modelo.model_name}'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().select_related('banco').get(pk=cuenta.pk)
    pago = consulta.filter(pk=pago_id).first()
    if not pago or not cuenta.activa or not cuenta.banco.activo or pago.moneda != cuenta.moneda:
        raise ValidationError('El pago debe existir y corresponder a la moneda de una cuenta activa.')
    from ventas.pagos_calculos import leer_tipos_pago
    if not leer_tipos_pago().get(pago.tipo_pago, {}).get('afecta_banco'):
        raise ValidationError('Esta forma de pago no afecta al banco y no admite cuenta bancaria.')
    if (CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=pago.fecha).exists()
            and not MovimientoInterno.objects.filter(cuenta=cuenta, origen=origen, pago_id=pago.pk).exists()):
        raise ValidationError('El mes está cerrado para la cuenta del pago.')
    movimiento, nuevo = MovimientoInterno.objects.get_or_create(origen=origen, pago_id=pago.pk,
        defaults={'cuenta': cuenta, 'fecha': pago.fecha, 'referencia': pago.referencia, 'monto': pago.monto * signo})
    if not nuevo and movimiento.cuenta_id != cuenta.pk:
        raise ValidationError('Este pago ya está vinculado a otra cuenta.')
    if origen == 'PROVEEDOR' and hasattr(pago, 'reverso'):
        reflejar_reverso_proveedor(pago, pago.reverso)
    return movimiento


def reflejar_reverso_proveedor(pago, reverso):
    original = MovimientoInterno.objects.filter(origen='PROVEEDOR', pago_id=pago.pk).first()
    if original:
        MovimientoInterno.objects.get_or_create(origen='REVERSO_PROVEEDOR', pago_id=reverso.pk,
            defaults={'cuenta_id': original.cuenta_id, 'fecha': reverso.fecha,
                      'referencia': original.referencia, 'monto': -original.monto})



def vincular_pagos_nuevos(usuario, origen, filas, pagos):
    if not any(fila.get('cuenta_bancaria') for fila in filas):
        return
    if len(filas) != len(pagos):
        raise ValidationError('Las cuentas bancarias no coinciden con los pagos registrados.')
    for fila, pago in zip(filas, pagos):
        cuenta = fila.get('cuenta_bancaria')
        if cuenta:
            vincular(usuario, cuenta, origen, pago.pk)


def reflejar_reversos_venta(origen, pagos):
    for pago in pagos:
        original = MovimientoInterno.objects.filter(origen=origen, pago_id=pago.pago_original_id).first()
        if original is None:
            cobro = getattr(pago.pago_original.documento, "cobro_compartido", None)
            if cobro and cobro.cuenta_id:
                from .models import CierreBancario
                cuenta = CuentaBancaria.objects.select_for_update().get(pk=cobro.cuenta_id)
                if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=pago.documento.fecha.replace(day=1)).exists():
                    raise ValidationError("El mes está cerrado para la cuenta del cobro compartido.")
                original = MovimientoInterno.objects.filter(origen="COBRO_COMPARTIDO", pago_id=cobro.pk).first()
                if original is None:
                    raise ValidationError("Falta el movimiento bancario del cobro compartido.")
        if original:
            MovimientoInterno.objects.get_or_create(origen=origen, pago_id=pago.pk,
                defaults={'cuenta_id': original.cuenta_id, 'fecha': pago.documento.fecha,
                          'referencia': pago.referencia, 'monto': pago.monto})
