from datetime import time
from django.core.exceptions import ValidationError
from django.db.models import Q
from citas.models import Cita
from .models import PromocionServicio


def citas_del_dia(cliente, fecha):
    return Cita.objects.filter(cliente=cliente, fecha=fecha).exclude(estado=Cita.Estado.CANCELADA)


def ofertas(cliente, fecha, hora=None, cita_id=None, entidad_id=None):
    if cita_id:
        cita = citas_del_dia(cliente, fecha).filter(pk=cita_id).first()
        if not cita:
            raise ValidationError("Selecciona una cita vigente de este cliente para la fecha de la factura.")
        hora = cita.hora
    candidatas = promociones_vigentes(fecha, entidad_id)
    resultado = {}
    for oferta in candidatas.order_by("-porcentaje", "pk"):
        dias = oferta.dias or ([oferta.dia] if oferta.dia else [])
        if dias and (hora is None or fecha.isoweekday() not in dias
                     or not oferta.hora_desde <= hora <= oferta.hora_hasta):
            continue
        resultado.setdefault(oferta.servicio_id, oferta)
    return resultado


def promociones_vigentes(fecha, entidad_id):
    candidatas = PromocionServicio.objects.filter(
        activa=True, desde__lte=fecha, hasta__gte=fecha, servicio__activo=True,
    ).filter(Q(entidad__isnull=True) | Q(entidad__activa=True, entidad_id=entidad_id) & Q(entidad__isnull=False))
    return candidatas


def horas_atencion(fecha, entidad_id=None):
    horas = set()
    for p in promociones_vigentes(fecha, entidad_id):
        if p.hora_desde is None or p.hora_hasta is None or fecha.isoweekday() not in (p.dias or [p.dia]):
            continue
        horas.add(p.hora_desde)
        horas.add(p.hora_hasta)
        horas.update(h for h in map(time, range(24)) if p.hora_desde <= h <= p.hora_hasta)
    return sorted(horas)
