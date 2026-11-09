from decimal import Decimal, localcontext
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from tasas_bcv.models import TasaBCV
from ventas.calculos import dinero
from ventas.pagos_calculos import leer_tipos_pago
from .models import Compra, PagoProveedor


def saldo_compra(compra):
    pagado = compra.pagos_proveedor.filter(reverso__isnull=True).aggregate(total=Sum('aplicado_factura'))['total'] or Decimal('0.00')
    return {'total': compra.total, 'pagado': pagado, 'saldo': dinero(compra.total - pagado)}


@transaction.atomic
def registrar_pago(*, compra_id, fecha, tipo_pago, monto, referencia, observacion, clave, usuario, cuenta_bancaria=None):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    compra = Compra.objects.select_for_update().get(pk=compra_id)
    anterior = PagoProveedor.objects.filter(clave=clave).first()
    if anterior:
        if (anterior.compra_id != compra_id or anterior.fecha != fecha or anterior.tipo_pago != int(tipo_pago)
                or anterior.monto != monto or anterior.referencia != referencia.strip().upper()
                or anterior.observacion != observacion.strip().upper()):
            raise ValidationError('La clave ya pertenece a otro pago.')
        if cuenta_bancaria:
            from bancos.vinculacion import vincular
            vincular(usuario, cuenta_bancaria, 'PROVEEDOR', anterior.pk)
        return anterior
    tipo = leer_tipos_pago().get(int(tipo_pago))
    if not tipo:
        raise ValidationError('La forma de pago no es válida.')
    tasa = TasaBCV.objects.filter(fecha=fecha).first()
    if tasa is None:
        raise ValidationError('No hay tasa Bs para la fecha del pago.')
    with localcontext() as contexto:
        contexto.prec = 60
        valor = Decimal(str(monto))
        if not valor.is_finite() or valor <= 0 or valor != dinero(valor) or valor >= Decimal('10000000000000000'):
            raise ValidationError('El monto debe ser positivo con hasta dos decimales.')
        aplicado = valor if tipo['moneda'] == compra.divisa else valor * tasa.tasa_bcv if tipo['moneda'] == 'USD' else valor / tasa.tasa_bcv
        if not aplicado.is_finite():
            raise ValidationError('Monto de pago inválido.')
        aplicado = dinero(aplicado)
    pago = PagoProveedor.objects.create(compra=compra, fecha=fecha, tipo_pago=tipo['id'],
        nombre_tipo_pago=tipo['nombre'].upper(), moneda=tipo['moneda'], monto=valor,
        tasa_cambio=tasa.tasa_bcv, aplicado_factura=aplicado, referencia=referencia,
        observacion=observacion, clave=clave, registrado_por=usuario.get_username())
    if cuenta_bancaria:
        from bancos.vinculacion import vincular
        vincular(usuario, cuenta_bancaria, 'PROVEEDOR', pago.pk)
    return pago


@transaction.atomic
def reversar_pago(*, pago_id, motivo, usuario):
    from django.utils import timezone
    from mysql_nuevo.bloqueos import serializar_operacion
    from .models import ReversoPagoProveedor
    serializar_operacion()
    pago = PagoProveedor.objects.select_for_update().get(pk=pago_id)
    reverso = ReversoPagoProveedor.objects.create(pago=pago, fecha=timezone.localdate(),
        motivo=motivo, registrado_por=usuario.get_username())
    from bancos.vinculacion import reflejar_reverso_proveedor
    reflejar_reverso_proveedor(pago, reverso)
    return reverso


def movimiento_proveedor(pago_id):
    from bancos.models import MovimientoInterno
    return MovimientoInterno.objects.filter(origen="PROVEEDOR", pago_id=pago_id)


def motivo_bloqueo_correccion(pago, movimiento):
    from bancos.models import CierreBancario, PartidaInterna

    if hasattr(pago, "reverso"):
        return "El pago ya fue reversado."
    if movimiento is not None:
        if PartidaInterna.objects.filter(movimiento_id=movimiento.pk).exists():
            return "El pago está conciliado y no se puede editar ni eliminar."
        if CierreBancario.objects.filter(cuenta_id=movimiento.cuenta_id, fecha_cierre__gte=movimiento.fecha).exists():
            return "El pago pertenece a un período bancario cerrado."
    return ""


@transaction.atomic
def corregir_pago(*, pago_id, motivo, usuario, reemplazo=None):
    """Retira el abono pendiente y, si corresponde, registra el reemplazo."""
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone
    from bancos.models import CierreBancario, CuentaBancaria
    from mysql_nuevo.bloqueos import serializar_operacion
    from .models import ReversoPagoProveedor

    if not usuario.is_superuser:
        raise PermissionDenied
    serializar_operacion()
    pago = PagoProveedor.objects.select_for_update().get(pk=pago_id)
    Compra.objects.select_for_update().get(pk=pago.compra_id)
    movimiento = movimiento_proveedor(pago.pk).first()
    nueva_cuenta = reemplazo.get("cuenta_bancaria") if reemplazo is not None else None
    cuentas_ids = {c for c in (movimiento.cuenta_id if movimiento else None,
                               nueva_cuenta.pk if nueva_cuenta else None) if c is not None}
    list(CuentaBancaria.objects.select_for_update().filter(pk__in=cuentas_ids).order_by("pk"))
    # Una vinculación concurrente puede haber creado el movimiento mientras se esperaba la cuenta.
    actual = movimiento_proveedor(pago.pk).first()
    if actual and actual.cuenta_id not in cuentas_ids:
        raise ValidationError("La cuenta del pago cambió. Vuelve a abrir el pago.")
    movimiento = actual
    bloqueo = motivo_bloqueo_correccion(pago, movimiento)
    if bloqueo:
        raise ValidationError(bloqueo)
    if nueva_cuenta and CierreBancario.objects.filter(
        cuenta_id=nueva_cuenta.pk, fecha_cierre__gte=reemplazo["fecha"],
    ).exists():
        raise ValidationError("La fecha seleccionada pertenece a un período bancario cerrado.")
    accion = "CORRECCIÓN" if reemplazo is not None else "ELIMINACIÓN"
    motivo = motivo.strip()
    if not motivo:
        raise ValidationError("Indica el motivo del cambio.")
    ReversoPagoProveedor.objects.create(pago=pago, fecha=timezone.localdate(),
        motivo=f"{accion}: {motivo}", registrado_por=usuario.get_username())
    if movimiento:
        # El débito pendiente se retira; no hubo un reintegro del banco que conciliar.
        movimiento.delete()
    if reemplazo is not None:
        return registrar_pago(compra_id=pago.compra_id, usuario=usuario, **reemplazo)
    return None
