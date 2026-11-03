from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import CuentaBancaria, Conciliacion, MovimientoBanco, MovimientoInterno, PartidaBanco, PartidaInterna


@transaction.atomic
def conciliar(usuario, cuenta, banco_ids, internos_ids, *, manual=False, por_monto=False):
    if not usuario.has_perm('bancos.add_conciliacion'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)
    banco_ids, internos_ids = set(banco_ids), set(internos_ids)
    banco = list(MovimientoBanco.objects.filter(cuenta=cuenta, pk__in=banco_ids, partida__isnull=True))
    internos = list(MovimientoInterno.objects.filter(cuenta=cuenta, pk__in=internos_ids, partida__isnull=True))
    if not banco or not internos or len(banco) != len(banco_ids) or len(internos) != len(internos_ids):
        raise ValidationError('Selecciona movimientos pendientes de la misma cuenta en ambos lados.')
    total = sum(m.monto for m in banco)
    diferencia = abs(total - sum(m.monto for m in internos))
    if diferencia > (Decimal('0.99') if manual else 0) or abs(total) >= 10**16:
        raise ValidationError('La diferencia no puede superar 0,99.' if manual else
                              'Los importes con signo de ambos lados deben coincidir.')
    grupo = Conciliacion.objects.create(cuenta=cuenta, usuario=usuario.get_username(), monto=total,
        metodo="MANUAL" if manual else "MONTO" if por_monto else "AUTO")
    PartidaBanco.objects.bulk_create([PartidaBanco(conciliacion=grupo, movimiento=m) for m in banco])
    PartidaInterna.objects.bulk_create([PartidaInterna(conciliacion=grupo, movimiento=m) for m in internos])
    return grupo


def sugerencias(cuenta):
    """Solo propone pares inequívocos; la confirmación vuelve a validar el saldo."""
    from collections import defaultdict
    banco = defaultdict(list)
    internos = defaultdict(list)
    for grupos, consulta, campo in [
        (banco, MovimientoBanco.objects.filter(cuenta=cuenta, partida__isnull=True), 'nro_transaccion'),
        (internos, MovimientoInterno.objects.filter(cuenta=cuenta, partida__isnull=True), 'referencia'),
    ]:
        for movimiento in consulta.iterator():
            referencia = getattr(movimiento, campo).strip().upper()
            if referencia:
                grupos[referencia, movimiento.monto].append(movimiento)
    return [(filas[0], internos[clave][0]) for clave, filas in banco.items()
            if len(filas) == len(internos.get(clave, ())) == 1]


@transaction.atomic
def conciliar_automaticamente(usuario, cuenta):
    if not usuario.has_perm('bancos.add_conciliacion'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)
    pares = sugerencias(cuenta)
    for banco, interno in pares:
        conciliar(usuario, cuenta, [banco.pk], [interno.pk])
    return len(pares)


def sugerencias_por_monto(cuenta):
    from collections import defaultdict
    banco, internos = defaultdict(list), defaultdict(list)
    for m in MovimientoBanco.objects.filter(cuenta=cuenta, partida__isnull=True):
        banco[m.monto].append(m)
    for m in MovimientoInterno.objects.filter(cuenta=cuenta, partida__isnull=True):
        internos[m.monto].append(m)
    return [(filas[0], internos[monto][0]) for monto, filas in banco.items()
            if len(filas) == len(internos.get(monto, ())) == 1
            and filas[0].nro_transaccion.strip().upper() != internos[monto][0].referencia.strip().upper()]


@transaction.atomic
def reversar(usuario, cuenta, grupo_id):
    from .models import CierreBancario, ReversoConciliacion
    from .cierres import detalle
    if not usuario.has_perm('bancos.add_reversoconciliacion'):
        raise PermissionDenied
    cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)
    try:
        grupo = Conciliacion.objects.get(pk=int(grupo_id), cuenta=cuenta, reverso__isnull=True)
    except (ValueError, Conciliacion.DoesNotExist):
        raise ValidationError('La conciliación no existe o ya fue reversada.')
    for cierre in CierreBancario.objects.filter(cuenta=cuenta).iterator():
        if any((g.get('id') if isinstance(g, dict) else g) == grupo.pk for g in cierre.resumen.get('conciliaciones', [])):
            raise ValidationError('No puedes reversar una conciliación incluida en un cierre mensual.')
    registro = ReversoConciliacion.objects.create(conciliacion=grupo, usuario=usuario.get_username(),
        movimientos={'banco': [detalle(p.movimiento, 'banco') for p in grupo.partidas_banco.select_related('movimiento')],
                     'sistema': [detalle(p.movimiento, 'sistema') for p in grupo.partidas_internas.select_related('movimiento')]})
    grupo.partidas_banco.all().delete()
    grupo.partidas_internas.all().delete()
    return registro
