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
