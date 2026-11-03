from calendar import monthrange

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CierreBancario, Conciliacion, CuentaBancaria, MovimientoBanco, MovimientoInterno


def detalle(movimiento, lado):
    return {'id': movimiento.pk, 'fecha': movimiento.fecha.isoformat(), 'monto': str(movimiento.monto),
            'referencia': movimiento.nro_transaccion if lado == 'banco' else movimiento.referencia}


def reporte(cuenta, hasta, desde=None):
    grupos = Conciliacion.objects.filter(cuenta=cuenta, reverso__isnull=True).exclude(
        partidas_banco__movimiento__fecha__gt=hasta).exclude(
        partidas_internas__movimiento__fecha__gt=hasta)
    visibles = grupos
    if desde:
        from django.db.models import Q
        visibles = grupos.filter(Q(partidas_banco__movimiento__fecha__gte=desde) |
            Q(partidas_internas__movimiento__fecha__gte=desde)).distinct()
    resumen = {'conciliaciones': [
        {'id': grupo.pk, 'monto': str(grupo.monto), 'usuario': grupo.usuario, 'metodo': grupo.get_metodo_display(),
         'banco': [detalle(p.movimiento, 'banco') for p in grupo.partidas_banco.all()],
         'sistema': [detalle(p.movimiento, 'sistema') for p in grupo.partidas_internas.all()]}
        for grupo in visibles.order_by('pk').prefetch_related(
            'partidas_banco__movimiento', 'partidas_internas__movimiento')
    ]}
    for clave, modelo in [('banco', MovimientoBanco), ('sistema', MovimientoInterno)]:
        filas = modelo.objects.filter(cuenta=cuenta, fecha__lte=hasta).exclude(partida__conciliacion__in=grupos)
        resumen[clave] = [detalle(m, clave) for m in filas.order_by('fecha', 'pk')]
    return resumen


@transaction.atomic
def cerrar(usuario, cuenta, fecha, saldo):
    if not usuario.has_perm('bancos.add_cierrebancario'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)
    if fecha.day != monthrange(fecha.year, fecha.month)[1] or fecha >= timezone.localdate():
        raise ValidationError('Selecciona el último día de un mes que ya terminó.')
    anterior = CierreBancario.objects.filter(cuenta=cuenta).first()
    if anterior:
        esperado = anterior.fecha_cierre
        mes = esperado.month % 12 + 1
        anio = esperado.year + (mes == 1)
        if (fecha.year, fecha.month) != (anio, mes):
            raise ValidationError('Selecciona el mes inmediatamente posterior al último cierre.')
    return CierreBancario.objects.create(cuenta=cuenta, fecha_cierre=fecha, saldo=saldo,
        resumen=reporte(cuenta, fecha), usuario=usuario.get_username())


def presentar_mes(resumen, desde):
    """Separa arrastres y limita grupos al mes sin alterar el cierre guardado."""
    inicio = desde.isoformat()
    return {
        'conciliaciones': [g for g in resumen['conciliaciones']
            if not isinstance(g, dict) or any(m['fecha'] >= inicio for m in g['banco'] + g['sistema'])],
        **{lado: [dict(m, arrastrado=m['fecha'] < inicio) for m in resumen[lado]]
           for lado in ('banco', 'sistema')},
    }
