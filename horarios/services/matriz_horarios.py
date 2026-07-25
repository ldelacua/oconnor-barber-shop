from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from horarios.models import Horario


HORA_APERTURA = "08:00"
ULTIMA_HORA_INICIO = "22:30"
INTERVALO_MINUTOS = 30

DIAS_VALIDOS = {1, 2, 3, 4, 5, 6, 7}


def texto_a_hora(valor):
    """
    Convierte un texto como '08:30' en datetime.time.
    """
    try:
        return datetime.strptime(valor, "%H:%M").time()
    except (TypeError, ValueError):
        raise ValidationError(
            f"La hora '{valor}' no tiene un formato válido."
        )


def hora_a_minutos(valor):
    """
    Convierte una hora en minutos desde las 00:00.

    Ejemplo:
    08:30 -> 510
    """
    return valor.hour * 60 + valor.minute


def minutos_a_hora(total_minutos):
    """
    Convierte minutos desde las 00:00 en datetime.time.

    Ejemplo:
    510 -> 08:30
    """
    hora = total_minutos // 60
    minuto = total_minutos % 60

    return datetime.strptime(
        f"{hora:02d}:{minuto:02d}",
        "%H:%M",
    ).time()


def validar_celda(valor):
    """
    Comprueba que la hora seleccionada:

    - tenga formato HH:MM;
    - esté entre 08:00 y 22:30;
    - corresponda a un intervalo de 30 minutos.
    """
    hora = texto_a_hora(valor)
    minutos = hora_a_minutos(hora)

    apertura = hora_a_minutos(
        texto_a_hora(HORA_APERTURA)
    )

    ultima_hora = hora_a_minutos(
        texto_a_hora(ULTIMA_HORA_INICIO)
    )

    if minutos < apertura or minutos > ultima_hora:
        raise ValidationError(
            f"La hora {valor} está fuera del rango permitido."
        )

    if minutos % INTERVALO_MINUTOS != 0:
        raise ValidationError(
            f"La hora {valor} no corresponde a un intervalo "
            f"de {INTERVALO_MINUTOS} minutos."
        )

    return minutos


def agrupar_celdas_consecutivas(celdas):
    """
    Convierte las celdas seleccionadas en rangos consecutivos.

    Ejemplo de entrada:

    [
        "08:00",
        "08:30",
        "09:00",
        "14:00",
        "14:30",
    ]

    Resultado:

    [
        (08:00, 09:30),
        (14:00, 15:00),
    ]
    """
    minutos_seleccionados = sorted(
        {
            validar_celda(celda)
            for celda in celdas
        }
    )

    if not minutos_seleccionados:
        return []

    bloques = []

    inicio = minutos_seleccionados[0]
    anterior = minutos_seleccionados[0]

    for minuto_actual in minutos_seleccionados[1:]:
        es_consecutivo = (
            minuto_actual
            == anterior + INTERVALO_MINUTOS
        )

        if es_consecutivo:
            anterior = minuto_actual
            continue

        bloques.append(
            (
                minutos_a_hora(inicio),
                minutos_a_hora(
                    anterior + INTERVALO_MINUTOS
                ),
            )
        )

        inicio = minuto_actual
        anterior = minuto_actual

    bloques.append(
        (
            minutos_a_hora(inicio),
            minutos_a_hora(
                anterior + INTERVALO_MINUTOS
            ),
        )
    )

    return bloques


def obtener_mensajes_error(error):
    """
    Convierte un ValidationError de Django en una lista
    sencilla de mensajes.
    """
    if hasattr(error, "message_dict"):
        mensajes = []

        for errores_campo in error.message_dict.values():
            mensajes.extend(
                str(mensaje)
                for mensaje in errores_campo
            )

        return mensajes

    return [
        str(mensaje)
        for mensaje in error.messages
    ]


def preparar_horarios(
    *,
    barbero,
    silla,
    seleccion,
    activo=True,
    observaciones="",
):
    """
    Convierte la selección de la matriz en objetos Horario.

    Todavía no guarda los objetos en la base de datos.
    Primero valida todos los bloques.
    """
    horarios = []
    errores = []

    if not isinstance(seleccion, dict):
        return [], [
            "La selección de horarios no tiene un formato válido."
        ]

    for dia_texto, celdas in seleccion.items():
        try:
            dia = int(dia_texto)
        except (TypeError, ValueError):
            errores.append(
                f"El día '{dia_texto}' no es válido."
            )
            continue

        if dia not in DIAS_VALIDOS:
            errores.append(
                f"El día '{dia_texto}' no es válido."
            )
            continue

        if not isinstance(celdas, list):
            errores.append(
                f"La selección del día {dia} no es válida."
            )
            continue

        try:
            bloques = agrupar_celdas_consecutivas(celdas)
        except ValidationError as error:
            errores.extend(
                obtener_mensajes_error(error)
            )
            continue

        for hora_inicio, hora_fin in bloques:
            horario = Horario(
                barbero=barbero,
                silla=silla,
                dia_semana=dia,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                activo=activo,
                observaciones=observaciones,
            )

            try:
                horario.full_clean()
            except ValidationError as error:
                nombre_dia = horario.get_dia_semana_display()

                rango = (
                    f"{hora_inicio.strftime('%H:%M')}–"
                    f"{hora_fin.strftime('%H:%M')}"
                )

                for mensaje in obtener_mensajes_error(error):
                    errores.append(
                        f"{nombre_dia} {rango}: {mensaje}"
                    )
            else:
                horarios.append(horario)

    if not horarios and not errores:
        errores.append(
            "Debe seleccionar al menos un bloque de horario."
        )

    return horarios, errores


@transaction.atomic
def crear_horarios_desde_matriz(
    *,
    barbero,
    silla,
    seleccion,
    activo=True,
    observaciones="",
):
    """
    Valida y guarda los horarios creados desde la matriz.

    Si alguno tiene errores, no se guarda ninguno.
    """
    horarios, errores = preparar_horarios(
        barbero=barbero,
        silla=silla,
        seleccion=seleccion,
        activo=activo,
        observaciones=observaciones,
    )

    if errores:
        return [], errores

    for horario in horarios:
        horario.save()

    return horarios, []
