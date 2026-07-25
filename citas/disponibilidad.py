from datetime import datetime, timedelta

from django.utils import timezone

from horarios.models import Horario

from .models import Cita


INTERVALO_MINUTOS = 30


def combinar_fecha_hora(fecha, hora):
    return datetime.combine(fecha, hora)


def obtener_horas_disponibles(
    barbero_id,
    servicio,
    fecha,
    cita_id=None,
):
    """
    Devuelve una lista de horas disponibles para un barbero,
    una fecha y un servicio determinado.
    """

    if not barbero_id or not servicio or not fecha:
        return []

    if fecha < timezone.localdate():
        return []

    dia_semana = fecha.isoweekday()

    horarios = Horario.objects.filter(
        barbero_id=barbero_id,
        dia_semana=dia_semana,
        activo=True,
    ).order_by("hora_inicio")

    if not horarios.exists():
        return []

    citas_existentes = (
        Cita.objects
        .select_related("servicio")
        .filter(
            barbero_id=barbero_id,
            fecha=fecha,
        )
        .exclude(estado=Cita.Estado.CANCELADA)
    )

    if cita_id:
        citas_existentes = citas_existentes.exclude(pk=cita_id)

    bloques_ocupados = []

    for cita in citas_existentes:
        inicio_cita = combinar_fecha_hora(
            cita.fecha,
            cita.hora,
        )

        fin_cita = inicio_cita + timedelta(
            minutes=cita.servicio.duracion
        )

        bloques_ocupados.append(
            (inicio_cita, fin_cita)
        )

    horas_disponibles = []

    for horario in horarios:
        inicio_horario = combinar_fecha_hora(
            fecha,
            horario.hora_inicio,
        )

        fin_horario = combinar_fecha_hora(
            fecha,
            horario.hora_fin,
        )

        hora_candidata = inicio_horario

        while hora_candidata < fin_horario:
            fin_servicio = hora_candidata + timedelta(
                minutes=servicio.duracion
            )

            if fin_servicio > fin_horario:
                break

            existe_conflicto = any(
                hora_candidata < fin_ocupado
                and fin_servicio > inicio_ocupado
                for inicio_ocupado, fin_ocupado
                in bloques_ocupados
            )

            if not existe_conflicto:
                valor = hora_candidata.strftime("%H:%M")

                if valor not in horas_disponibles:
                    horas_disponibles.append(valor)

            hora_candidata += timedelta(
                minutes=INTERVALO_MINUTOS
            )

    return horas_disponibles
