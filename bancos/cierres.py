from calendar import monthrange
from decimal import Decimal

from django.db.models import Sum

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


def saldos_apertura(anterior):
    return (
        anterior.saldo if anterior else None,
        Decimal(anterior.resumen['saldos']['final_sistema'])
        if anterior and anterior.resumen.get('saldos') else None,
    )


def calcular_saldos(cuenta, fecha, saldo, saldo_inicial_banco=None, saldo_inicial_sistema=None):
    if fecha.day != monthrange(fecha.year, fecha.month)[1] or fecha >= timezone.localdate():
        raise ValidationError('Selecciona el último día de un mes que ya terminó.')
    anterior = CierreBancario.objects.filter(cuenta=cuenta).first()
    desde = fecha.replace(day=1)
    if anterior:
        ultimo = anterior.fecha_cierre
        mes = ultimo.month % 12 + 1
        if (fecha.year, fecha.month) != (ultimo.year + (mes == 1), mes):
            raise ValidationError('Selecciona el mes inmediatamente posterior al último cierre.')
    apertura_banco, apertura_sistema = saldos_apertura(anterior)
    inicial_banco = apertura_banco if apertura_banco is not None else saldo_inicial_banco
    inicial_sistema = apertura_sistema if apertura_sistema is not None else saldo_inicial_sistema
    if inicial_banco is None or inicial_sistema is None:
        raise ValidationError('Indica los saldos iniciales que no se pueden recuperar del cierre anterior.')

    resumen = reporte(cuenta, fecha)

    def movimiento_mes(modelo):
        return modelo.objects.filter(cuenta=cuenta, fecha__range=(desde, fecha)).aggregate(
            total=Sum('monto', default=0))['total']

    def pendiente(lado):
        return sum((Decimal(fila['monto']) for fila in resumen[lado]), Decimal('0.00'))

    neto_banco = movimiento_mes(MovimientoBanco)
    neto_sistema = movimiento_mes(MovimientoInterno)
    calculado_banco = inicial_banco + neto_banco
    final_sistema = inicial_sistema + neto_sistema
    pendiente_banco = pendiente('banco')
    pendiente_sistema = pendiente('sistema')
    ajustado_banco = saldo + pendiente_sistema
    ajustado_sistema = final_sistema + pendiente_banco
    resumen['saldos'] = {
        clave: format(valor, '.2f') for clave, valor in {
            'inicial_banco': inicial_banco, 'inicial_sistema': inicial_sistema,
            'neto_banco': neto_banco, 'neto_sistema': neto_sistema,
            'final_extracto': saldo, 'calculado_banco': calculado_banco,
            'final_sistema': final_sistema, 'pendiente_banco': pendiente_banco,
            'pendiente_sistema': pendiente_sistema, 'ajustado_banco': ajustado_banco,
            'ajustado_sistema': ajustado_sistema, 'diferencia_extracto': saldo - calculado_banco,
            'diferencia_final': ajustado_banco - ajustado_sistema,
        }.items()
    }
    return resumen


def errores_cuadre(resumen):
    saldos = resumen['saldos']
    errores = []
    if Decimal(saldos['diferencia_extracto']):
        errores.append('El saldo final del extracto no coincide con el saldo inicial más los movimientos cargados.')
    if resumen['banco']:
        errores.append('Hay movimientos del banco sin conciliar. Revisa si falta registrarlos en el sistema.')
    if Decimal(saldos['diferencia_final']):
        errores.append('Queda una diferencia entre los saldos ajustados. Revisa los movimientos y los saldos iniciales.')
    return errores


@transaction.atomic
def cerrar(usuario, cuenta, fecha, saldo, saldo_inicial_banco=None, saldo_inicial_sistema=None):
    if not usuario.has_perm('bancos.add_cierrebancario'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)
    resumen = calcular_saldos(cuenta, fecha, saldo, saldo_inicial_banco, saldo_inicial_sistema)
    errores = errores_cuadre(resumen)
    if errores:
        raise ValidationError(errores)
    return CierreBancario.objects.create(cuenta=cuenta, fecha_cierre=fecha, saldo=saldo,
        resumen=resumen, usuario=usuario.get_username())


def presentar_mes(resumen, desde):
    """Separa arrastres y limita grupos al mes sin alterar el cierre guardado."""
    inicio = desde.isoformat()
    return {
        'conciliaciones': [g for g in resumen['conciliaciones']
            if not isinstance(g, dict) or any(m['fecha'] >= inicio for m in g['banco'] + g['sistema'])],
        **{lado: [dict(m, arrastrado=m['fecha'] < inicio) for m in resumen[lado]]
           for lado in ('banco', 'sistema')},
    }
