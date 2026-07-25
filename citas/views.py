from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from horarios.models import Horario
from servicios.models import Servicio

from .disponibilidad import obtener_horas_disponibles
from .forms import CitaForm
from .models import Cita


@login_required
def agenda_citas(request):
    fecha_texto = request.GET.get("fecha")

    if fecha_texto:
        try:
            fecha_seleccionada = datetime.strptime(
                fecha_texto,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            fecha_seleccionada = timezone.localdate()
    else:
        fecha_seleccionada = timezone.localdate()

    dia_semana = fecha_seleccionada.isoweekday()

    horarios = (
        Horario.objects.select_related(
            "barbero",
            "silla",
        )
        .filter(
            dia_semana=dia_semana,
            activo=True,
        )
        .order_by(
            "hora_inicio",
            "barbero",
        )
    )

    barberos = []

    for horario in horarios:
        if horario.barbero not in barberos:
            barberos.append(horario.barbero)

    citas = (
        Cita.objects.select_related(
            "cliente",
            "barbero",
            "servicio",
        )
        .prefetch_related("servicios")
        .filter(
            fecha=fecha_seleccionada,
        )
        .exclude(
            estado=Cita.Estado.CANCELADA,
        )
        .order_by("hora")
    )

    franjas = []
    intervalo_minutos = 15

    if horarios.exists():
        primera_hora = min(
            horario.hora_inicio
            for horario in horarios
        )

        ultima_hora = max(
            horario.hora_fin
            for horario in horarios
        )

        momento_actual = datetime.combine(
            fecha_seleccionada,
            primera_hora,
        )

        momento_final = datetime.combine(
            fecha_seleccionada,
            ultima_hora,
        )

        while momento_actual < momento_final:
            hora_texto = momento_actual.strftime("%H:%M")
            celdas = []

            for barbero in barberos:
                horario_barbero = next(
                    (
                        horario
                        for horario in horarios
                        if (
                            horario.barbero_id == barbero.id
                            and horario.hora_inicio
                            <= momento_actual.time()
                            < horario.hora_fin
                        )
                    ),
                    None,
                )

                inicio_franja = momento_actual
                fin_franja = momento_actual + timedelta(
                    minutes=intervalo_minutos
                )

                cita_inicial = None
                cita_ocupante = None

                for cita in citas:
                    if cita.barbero_id != barbero.id:
                        continue

                    inicio_cita = datetime.combine(
                        fecha_seleccionada,
                        cita.hora,
                    )

                    fin_cita = inicio_cita + timedelta(
                        minutes=cita.duracion_total
                    )

                    if inicio_cita == inicio_franja:
                        cita_inicial = cita

                    if (
                        inicio_franja < fin_cita
                        and fin_franja > inicio_cita
                    ):
                        cita_ocupante = cita
                        break

                celdas.append(
                    {
                        "barbero": barbero,
                        "disponible": (
                            horario_barbero is not None
                            and cita_ocupante is None
                        ),
                        "ocupada": cita_ocupante is not None,
                        "cita": cita_inicial,
                        "cita_ocupante": cita_ocupante,
                    }
                )

            franjas.append(
                {
                    "hora": hora_texto,
                    "celdas": celdas,
                }
            )

            momento_actual += timedelta(
                minutes=intervalo_minutos
            )

    contexto = {
        "fecha_seleccionada": fecha_seleccionada,
        "fecha_anterior": (
            fecha_seleccionada - timedelta(days=1)
        ),
        "fecha_siguiente": (
            fecha_seleccionada + timedelta(days=1)
        ),
        "barberos": barberos,
        "franjas": franjas,
    }

    return render(
        request,
        "citas/agenda.html",
        contexto,
    )


@login_required
def listar_citas(request):
    citas = Cita.objects.select_related(
        "cliente",
        "barbero",
        "servicio",
    ).all()

    estado = request.GET.get("estado")
    fecha = request.GET.get("fecha")
    barbero = request.GET.get("barbero")

    if estado:
        citas = citas.filter(estado=estado)

    if fecha:
        citas = citas.filter(fecha=fecha)

    if barbero:
        citas = citas.filter(barbero_id=barbero)

    contexto = {
        "citas": citas,
        "estados": Cita.Estado.choices,
    }

    return render(
        request,
        "citas/lista.html",
        contexto,
    )


@login_required
def crear_cita(request):
    fecha_inicial = request.GET.get("fecha")
    hora_inicial = request.GET.get("hora")
    barbero_inicial = request.GET.get("barbero")

    initial = {}

    if fecha_inicial:
        initial["fecha"] = fecha_inicial

    if hora_inicial:
        initial["hora"] = hora_inicial

    if barbero_inicial:
        initial["barbero"] = barbero_inicial

    if request.method == "POST":
        form = CitaForm(request.POST)

        if form.is_valid():
            cita = form.save()

            messages.success(
                request,
                "La cita fue creada correctamente.",
            )

            url_agenda = reverse(
                "citas:agenda_citas"
            )

            fecha_cita = cita.fecha.strftime(
                "%Y-%m-%d"
            )

            return redirect(
                f"{url_agenda}?fecha={fecha_cita}"
            )
    else:
        form = CitaForm(initial=initial)

    return render(
        request,
        "citas/formulario.html",
        {
            "form": form,
            "titulo": "Nueva cita",
            "texto_boton": "Guardar cita",
        },
    )


@login_required
def editar_cita(request, cita_id):
    cita = get_object_or_404(
        Cita,
        pk=cita_id,
    )

    if request.method == "POST":
        form = CitaForm(
            request.POST,
            instance=cita,
        )

        if form.is_valid():
            cita = form.save()

            messages.success(
                request,
                "La cita fue actualizada correctamente.",
            )

            url_agenda = reverse(
                "citas:agenda_citas"
            )

            fecha_cita = cita.fecha.strftime(
                "%Y-%m-%d"
            )

            return redirect(
                f"{url_agenda}?fecha={fecha_cita}"
            )
    else:
        form = CitaForm(instance=cita)

    return render(
        request,
        "citas/formulario.html",
        {
            "form": form,
            "titulo": "Editar cita",
            "texto_boton": "Actualizar cita",
        },
    )


@login_required
def eliminar_cita(request, cita_id):
    cita = get_object_or_404(
        Cita,
        pk=cita_id,
    )

    fecha_cita = cita.fecha.strftime(
        "%Y-%m-%d"
    )

    if request.method == "POST":
        cita.delete()

        messages.success(
            request,
            "La cita fue eliminada correctamente.",
        )

        url_agenda = reverse(
            "citas:agenda_citas"
        )

        return redirect(
            f"{url_agenda}?fecha={fecha_cita}"
        )

    return render(
        request,
        "citas/eliminar.html",
        {
            "cita": cita,
        },
    )


@login_required
def cambiar_estado_cita(request, cita_id):
    cita = get_object_or_404(
        Cita,
        pk=cita_id,
    )

    if request.method == "POST":
        nuevo_estado = request.POST.get(
            "estado"
        )

        estados_validos = {
            valor
            for valor, etiqueta
            in Cita.Estado.choices
        }

        if nuevo_estado in estados_validos:
            cita.estado = nuevo_estado
            cita.save(
                update_fields=["estado"]
            )

            messages.success(
                request,
                "El estado de la cita fue actualizado.",
            )
        else:
            messages.error(
                request,
                "El estado seleccionado no es válido.",
            )

    url_agenda = reverse(
        "citas:agenda_citas"
    )

    fecha_cita = cita.fecha.strftime(
        "%Y-%m-%d"
    )

    return redirect(
        f"{url_agenda}?fecha={fecha_cita}"
    )


@login_required
def consultar_disponibilidad(request):
    barbero_id = request.GET.get("barbero")
    servicios_ids = request.GET.getlist("servicios")
    fecha_texto = request.GET.get("fecha")
    cita_id = request.GET.get("cita")

    if (
        not barbero_id
        or not servicios_ids
        or not fecha_texto
    ):
        return JsonResponse(
            {
                "horas": [],
                "error": (
                    "Debes seleccionar barbero, "
                    "al menos un servicio y fecha."
                ),
            },
            status=400,
        )

    try:
        fecha = datetime.strptime(
            fecha_texto,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return JsonResponse(
            {
                "horas": [],
                "error": "La fecha no es válida.",
            },
            status=400,
        )

    try:
        servicios_ids = [
            int(servicio_id)
            for servicio_id in servicios_ids
        ]
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "horas": [],
                "error": (
                    "Uno o más servicios seleccionados "
                    "no son válidos."
                ),
            },
            status=400,
        )

    servicios = list(
        Servicio.objects.filter(
            pk__in=servicios_ids,
            activo=True,
        )
    )

    if len(servicios) != len(set(servicios_ids)):
        return JsonResponse(
            {
                "horas": [],
                "error": (
                    "Uno o más servicios no existen "
                    "o están inactivos."
                ),
            },
            status=404,
        )

    duracion_total = sum(
        servicio.duracion
        for servicio in servicios
    )

    precio_total = sum(
        servicio.precio
        for servicio in servicios
    )

    horas = obtener_horas_disponibles(
        barbero_id=barbero_id,
        servicios=servicios,
        fecha=fecha,
        cita_id=cita_id,
    )

    return JsonResponse(
        {
            "horas": horas,
            "duracion": duracion_total,
            "precio": str(precio_total),
        }
    )