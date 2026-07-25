from datetime import datetime, timedelta

from django.utils import timezone

from horarios.models import Horario

from .models import Cita


INTERVALO_MINUTOS = 15


def combinar_fecha_hora(fecha, hora):
    return datetime.combine(fecha, hora)


def calcular_duracion_servicios(
    servicio=None,
    servicios=None,
):
    """
    Calcula la duración total de uno o varios servicios.
    """
    if servicios is not None:
        return sum(
            int(servicio_seleccionado.duracion or 0)
            for servicio_seleccionado in servicios
        )

    if servicio is not None:
        return int(servicio.duracion or 0)

    return 0


def calcular_duracion_cita(cita):
    """
    Calcula la duración total de una cita existente.
    Prioriza el campo ManyToMany servicios y conserva
    compatibilidad con el campo antiguo servicio.
    """
    servicios_cita = list(cita.servicios.all())

    if servicios_cita:
        return sum(
            int(servicio.duracion or 0)
            for servicio in servicios_cita
        )

    if cita.servicio_id:
        return int(cita.servicio.duracion or 0)

    return 0


def obtener_horas_disponibles(
    barbero_id,
    fecha,
    servicio=None,
    servicios=None,
    cita_id=None,
):
    """
    Devuelve una lista de horas disponibles para un barbero,
    una fecha y uno o varios servicios.
    """

    if not barbero_id or not fecha:
        return []

    duracion_total = calcular_duracion_servicios(
        servicio=servicio,
        servicios=servicios,
    )

    if duracion_total <= 0:
        return []

    if fecha < timezone.localdate():
        return []

    dia_semana = fecha.isoweekday()

    horarios = (
        Horario.objects
        .filter(
            barbero_id=barbero_id,
            dia_semana=dia_semana,
            activo=True,
        )
        .order_by("hora_inicio")
    )

    if not horarios.exists():
        return []

    citas_existentes = (
        Cita.objects
        .select_related("servicio")
        .prefetch_related("servicios")
        .filter(
            barbero_id=barbero_id,
            fecha=fecha,
        )
        .exclude(
            estado=Cita.Estado.CANCELADA,
        )
    )

    if cita_id:
        citas_existentes = citas_existentes.exclude(
            pk=cita_id
        )

    bloques_ocupados = []

    for cita in citas_existentes:
        inicio_cita = combinar_fecha_hora(
            cita.fecha,
            cita.hora,
        )

        duracion_cita = calcular_duracion_cita(cita)

        if duracion_cita <= 0:
            continue

        fin_cita = inicio_cita + timedelta(
            minutes=duracion_cita
        )

        bloques_ocupados.append(
            (
                inicio_cita,
                fin_cita,
            )
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
            fin_servicios = (
                hora_candidata
                + timedelta(minutes=duracion_total)
            )

            if fin_servicios > fin_horario:
                break

            if fecha == timezone.localdate():
                ahora = timezone.localtime()

                ahora_sin_zona = ahora.replace(
                    tzinfo=None,
                    second=0,
                    microsecond=0,
                )

                if hora_candidata < ahora_sin_zona:
                    hora_candidata += timedelta(
                        minutes=INTERVALO_MINUTOS
                    )
                    continue

            existe_conflicto = any(
                hora_candidata < fin_ocupado
                and fin_servicios > inicio_ocupado
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