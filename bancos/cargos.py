from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .conciliacion import conciliar
from .models import CargoBancario, CierreBancario, CuentaBancaria, MovimientoBanco, MovimientoInterno


@transaction.atomic
def registrar_cargo(usuario, cuenta_id, movimiento_id, concepto):
    if not usuario.has_perms(('bancos.add_movimientointerno', 'bancos.add_conciliacion')):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().select_related('banco').get(pk=cuenta_id)
    banco = MovimientoBanco.objects.filter(pk=movimiento_id, cuenta=cuenta, monto__lt=0,
                                          partida__isnull=True).first()
    if not banco or CargoBancario.objects.filter(movimiento_banco=banco).exists():
        raise ValidationError('El débito ya fue procesado o no está pendiente en esta cuenta.')
    if not cuenta.activa or not cuenta.banco.activo:
        raise ValidationError('La cuenta y el banco deben estar activos.')
    if banco.fecha > timezone.localdate():
        raise ValidationError('No puedes registrar un cargo con fecha futura.')
    if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=banco.fecha).exists():
        raise ValidationError('El período de este movimiento ya está cerrado.')
    if MovimientoInterno.objects.filter(cuenta=cuenta, partida__isnull=True,
                                        referencia__iexact=banco.nro_transaccion[:100], monto=banco.monto).exists():
        raise ValidationError('Ya hay un movimiento pendiente con la misma referencia e importe. Concilia ese movimiento.')
    concepto = concepto.strip()
    if not concepto or len(concepto) > 200:
        raise ValidationError('Indica un concepto de hasta 200 caracteres.')
    interno = MovimientoInterno.objects.create(
        cuenta=cuenta, origen='CARGO_BANCARIO', pago_id=banco.pk, fecha=banco.fecha,
        referencia=banco.nro_transaccion[:100], monto=banco.monto,
    )
    cargo = CargoBancario.objects.create(movimiento_banco=banco, movimiento_interno=interno,
                                        concepto=concepto, usuario=usuario.get_username())
    conciliar(usuario, cuenta, [banco.pk], [interno.pk], manual=True)
    return cargo


@transaction.atomic
def anular_cargo(usuario, cuenta_id, movimiento_id, motivo):
    from .models import AnulacionCargoBancario, PartidaBanco, PartidaInterna

    if not usuario.has_perms(('bancos.delete_movimientointerno', 'bancos.add_reversoconciliacion')):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta_id)
    cargo = CargoBancario.objects.select_related('movimiento_banco', 'movimiento_interno').filter(
        movimiento_banco_id=movimiento_id, movimiento_banco__cuenta=cuenta,
    ).first()
    if not cargo:
        raise ValidationError('El cargo ya no está registrado.')
    banco, interno = cargo.movimiento_banco, cargo.movimiento_interno
    if CierreBancario.objects.filter(cuenta=cuenta, fecha_cierre__gte=min(banco.fecha, interno.fecha)).exists():
        raise ValidationError('El período de este cargo ya está cerrado.')
    if (PartidaBanco.objects.filter(movimiento=banco).exists()
            or PartidaInterna.objects.filter(movimiento=interno).exists()):
        raise ValidationError('Reversa primero las conciliaciones asociadas a este cargo.')
    motivo = motivo.strip()
    if not motivo or len(motivo) > 250:
        raise ValidationError('Indica el motivo de la anulación.')
    AnulacionCargoBancario.objects.create(
        cuenta=cuenta, usuario=usuario.get_username(), motivo=motivo,
        datos_cargo={'cargo_id': cargo.pk, 'banco_id': banco.pk, 'interno_id': interno.pk,
                     'fecha': interno.fecha.isoformat(), 'importe': str(interno.monto),
                     'referencia': banco.nro_transaccion, 'concepto': cargo.concepto,
                     'usuario_original': cargo.usuario, 'registrado_en': cargo.registrado_en.isoformat()},
    )
    cargo.delete()
    interno.delete()
