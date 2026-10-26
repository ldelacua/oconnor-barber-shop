"""Lectura y actualización atómica de la semana de un prestador."""
import hashlib
import json
from datetime import datetime, time, timedelta
from math import gcd

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from barberos.models import Barbero
from horarios.models import Horario, Silla


CAMPOS_VERSION = ('pk', 'silla_id', 'dia_semana', 'hora_inicio', 'hora_fin', 'activo', 'observaciones')


def version_semana(prestador, horarios):
    datos = {
        'prestador': prestador.pk, 'silla': prestador.silla_id,
        'silla_activa': bool(prestador.silla_id and prestador.silla.activa),
        'horarios': [[str(getattr(h, c)) for c in CAMPOS_VERSION] for h in sorted(horarios, key=lambda h: h.pk)],
    }
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def minuto(hora):
    return hora.hour * 60 + hora.minute


def texto(minutos):
    return f'{minutos // 60:02d}:{minutos % 60:02d}'


def hora(minutos):
    return time(minutos // 60, minutos % 60)


def configurar_rejilla(horarios):
    paso, inicio, fin = 30, 8 * 60, 23 * 60
    for h in horarios:
        if h.hora_inicio.second or h.hora_fin.second or h.hora_inicio.microsecond or h.hora_fin.microsecond:
            raise ValidationError('Hay un horario con segundos. Corrígelo antes de utilizar la matriz semanal; no se ha cambiado ningún horario.')
        if h.hora_fin <= h.hora_inicio or h.dia_semana not in range(1, 8):
            raise ValidationError('Hay un horario con día u horas inválidas. Corrígelo antes de utilizar la matriz semanal.')
        inicio = min(inicio, minuto(h.hora_inicio))
        fin = max(fin, minuto(h.hora_fin))
        paso = gcd(paso, gcd(minuto(h.hora_inicio), minuto(h.hora_fin)))
    return {'inicio': inicio, 'fin': fin, 'paso': paso}


def seleccion_actual(horarios, rejilla):
    seleccion = {str(d): [] for d in range(1, 8)}
    for h in horarios:
        if h.activo:
            seleccion[str(h.dia_semana)].extend(texto(m) for m in range(minuto(h.hora_inicio), minuto(h.hora_fin), rejilla['paso']))
    return {d: sorted(set(horas)) for d, horas in seleccion.items()}


def validar_seleccion(seleccion, rejilla):
    if not isinstance(seleccion, dict) or any(d not in {str(n) for n in range(1, 8)} for d in seleccion):
        raise ValidationError('La selección semanal no tiene un formato válido.')
    permitidas = {texto(m): m for m in range(rejilla['inicio'], rejilla['fin'], rejilla['paso'])}
    normalizada = {}
    for d in map(str, range(1, 8)):
        horas = seleccion.get(d, [])
        if not isinstance(horas, list) or len(horas) > len(permitidas) or any(not isinstance(h, str) or h not in permitidas for h in horas):
            raise ValidationError('La selección contiene horas fuera de la matriz. Recarga la pantalla y vuelve a seleccionar.')
        normalizada[d] = sorted(set(horas))
    return normalizada


def rangos_seleccion(seleccion, rejilla):
    rangos = []
    for d, valores in validar_seleccion(seleccion, rejilla).items():
        minutos = sorted(int(v[:2]) * 60 + int(v[3:]) for v in valores)
        if not minutos:
            continue
        inicio = anterior = minutos[0]
        for m in minutos[1:]:
            if m != anterior + rejilla['paso']:
                rangos.append((int(d), hora(inicio), hora(anterior + rejilla['paso'])))
                inicio = m
            anterior = m
        rangos.append((int(d), hora(inicio), hora(anterior + rejilla['paso'])))
    return rangos


def cubre_cita(rangos, inicio, fin):
    """Comprueba cobertura continua, incluso entre bloques contiguos."""
    if fin <= inicio:
        return False
    actual = inicio
    while actual < fin:
        limite = min(fin, datetime.combine(actual.date() + timedelta(days=1), time.min))
        cursor = actual
        for dia, desde, hasta in sorted(rangos):
            if dia != actual.isoweekday():
                continue
            a = datetime.combine(actual.date(), desde)
            b = datetime.combine(actual.date(), hasta)
            if a <= cursor < b:
                cursor = max(cursor, b)
        if cursor < limite:
            return False
        actual = limite
    return True


def _citas_futuras(prestador_id, hoy):
    try:
        Cita = apps.get_model('citas', 'Cita')
    except LookupError:
        return []  # Permite instalar Horarios en un proyecto sin Citas.
    return (Cita.objects.filter(barbero_id=prestador_id, fecha__gte=hoy)
            .exclude(estado__in=['cancelada', 'finalizada'])
            .select_related('servicio').prefetch_related('servicios').order_by('fecha', 'hora'))


def comprobar_citas(prestador_id, anteriores, nuevos):
    ahora = timezone.localtime().replace(tzinfo=None)
    conflictos = []
    for cita in _citas_futuras(prestador_id, ahora.date()):
        inicio = datetime.combine(cita.fecha, cita.hora)
        fin = inicio + timedelta(minutes=max(1, int(cita.duracion_total)))
        if fin <= ahora:
            continue
        if cubre_cita(anteriores, inicio, fin) and not cubre_cita(nuevos, inicio, fin):
            conflictos.append(f'Cita {cita.pk}: {cita.fecha:%d/%m/%Y} a las {cita.hora:%H:%M}')
    if conflictos:
        detalle = '; '.join(conflictos[:5])
        if len(conflictos) > 5:
            detalle += f'; y {len(conflictos) - 5} más'
        raise ValidationError('No puedes quitar estas horas porque tienen citas pendientes o confirmadas. Reprograma o cancela esas citas primero. ' + detalle)


@transaction.atomic
def guardar_semana(*, prestador_id, seleccion, version, observaciones=''):
    from mysql_nuevo.bloqueos import serializar_operacion
    serializar_operacion()
    prestador = Barbero.objects.select_for_update().get(pk=prestador_id)
    if not prestador.silla_id:
        raise ValidationError('El prestador no tiene silla asignada. Asígnala en Prest de Servicio.')
    silla = Silla.objects.select_for_update().get(pk=prestador.silla_id)
    prestador.silla = silla
    if not silla.activa:
        raise ValidationError('La silla asignada está inactiva. Actívala o cambia la asignación en Prest de Servicio.')
    anteriores = list(Horario.objects.select_for_update().filter(barbero=prestador).order_by('pk'))
    if version_semana(prestador, anteriores) != version:
        raise ValidationError('El horario o la silla cambió desde que abriste la pantalla. Pulsa Recargar antes de guardar.')
    rejilla = configurar_rejilla(anteriores)
    nuevos = rangos_seleccion(seleccion, rejilla)
    activos = [h for h in anteriores if h.activo]
    anteriores_rangos = [(h.dia_semana, h.hora_inicio, h.hora_fin) for h in activos]
    comprobar_citas(prestador.pk, anteriores_rangos, nuevos)
    otros = Horario.objects.filter(silla=silla, activo=True).exclude(barbero=prestador)
    for dia, desde, hasta in nuevos:
        if otros.filter(dia_semana=dia, hora_inicio__lt=hasta, hora_fin__gt=desde).exists():
            nombre = dict(Horario.DIAS_SEMANA)[dia]
            raise ValidationError(f'{nombre} {desde:%H:%M}–{hasta:%H:%M}: la silla ya está ocupada por otro prestador.')
    # Mantener los registros idénticos conserva sus IDs y observaciones.
    conservar = []
    pendientes = list(nuevos)
    for h in activos:
        clave = (h.dia_semana, h.hora_inicio, h.hora_fin)
        if h.silla_id == silla.pk and clave in pendientes:
            conservar.append(h.pk)
            pendientes.remove(clave)
    desactivar = [h.pk for h in activos if h.pk not in conservar]
    if desactivar:
        Horario.objects.filter(pk__in=desactivar).update(activo=False)
    creados = 0
    for dia, desde, hasta in pendientes:
        inactivo = next((h for h in anteriores if not h.activo and h.silla_id == silla.pk and
                         (h.dia_semana, h.hora_inicio, h.hora_fin) == (dia, desde, hasta)), None)
        if inactivo:
            inactivo.activo = True
            inactivo.save()
        else:
            Horario.objects.create(barbero=prestador, silla=silla, dia_semana=dia,
                                   hora_inicio=desde, hora_fin=hasta, activo=True,
                                   observaciones=observaciones)
        creados += 1
    return {'agregados': creados, 'desactivados': len(desactivar)}
