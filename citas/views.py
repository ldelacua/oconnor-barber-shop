from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .buscador_clientes import buscar_clientes
from horarios.models import Horario
from servicios.models import Servicio

from .disponibilidad import (
    obtener_horas_disponibles,
    MARGEN_ENTRE_CITAS,
)
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

    ahora = timezone.localtime()
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
            if (
                fecha_seleccionada == ahora.date()
                and momento_actual.time() < ahora.time()
            ):
                momento_actual += timedelta(
                    minutes=intervalo_minutos
                )
                continue

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
                        minutes=(
                            cita.duracion_total
                            + MARGEN_ENTRE_CITAS
                        )
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
    hoy = timezone.localdate()
    fecha_seleccionada = hoy
    fecha_texto = request.GET.get("fecha", "")

    if fecha_texto:
        try:
            fecha_seleccionada = datetime.strptime(fecha_texto, "%Y-%m-%d").date()
        except ValueError:
            messages.warning(request, "La fecha no es válida. Se muestran las citas de hoy.")

    if fecha_seleccionada < hoy:
        messages.warning(request, "No puedes consultar fechas anteriores a hoy.")
        fecha_seleccionada = hoy

    citas = (
        Cita.objects.select_related("cliente", "barbero", "servicio")
        .prefetch_related("servicios")
        .filter(fecha=fecha_seleccionada)
        .order_by("hora")
    )
    estado = request.GET.get("estado", "")
    barbero = request.GET.get("barbero", "")
    if estado:
        citas = citas.filter(estado=estado)
    if barbero:
        citas = citas.filter(barbero_id=barbero)

    return render(request, "citas/lista.html", {
        "citas": citas,
        "estados": Cita.Estado.choices,
        "fecha_seleccionada": fecha_seleccionada,
        "hoy": hoy,
        "estado_seleccionado": estado,
        "barbero_seleccionado": barbero,
    })


@login_required
def crear_cita(request):
    from django.core import signing
    from .agenda_forms import CitaAgendaForm

    salt = "citas.seleccion_agenda"
    token = ""
    seleccion = None

    if request.method == "POST":
        token = request.POST.get("seleccion_agenda", "")
        if token:
            try:
                datos = signing.loads(token, salt=salt, max_age=14400)
                if datos["usuario"] != request.user.pk:
                    raise signing.BadSignature("Usuario diferente")
                seleccion = datos["seleccion"]
            except (signing.BadSignature, KeyError, TypeError, ValueError):
                messages.error(request, "La selección ha caducado o no es válida. Elige el hueco de nuevo.")
                return redirect("citas:agenda_citas")
    else:
        valores = {nombre: request.GET.get(nombre) for nombre in ("barbero", "fecha", "hora")}
        if any(valores.values()):
            try:
                if not all(valores.values()):
                    raise ValueError("Selección incompleta")
                seleccion = {
                    "barbero": str(int(valores["barbero"])),
                    "fecha": datetime.strptime(valores["fecha"], "%Y-%m-%d").date().isoformat(),
                    "hora": datetime.strptime(valores["hora"], "%H:%M").strftime("%H:%M"),
                }
                if datetime.strptime(seleccion["fecha"], "%Y-%m-%d").date() < timezone.localdate():
                    raise ValueError("Fecha pasada")
            except (ValueError, TypeError):
                messages.error(request, "Selecciona un hueco válido en Agenda.")
                return redirect("citas:agenda_citas")
            token = signing.dumps({"usuario": request.user.pk, "seleccion": seleccion}, salt=salt)

    data = request.POST if request.method == "POST" else None
    if seleccion:
        form = CitaAgendaForm(data, seleccion=seleccion)
    else:
        form = CitaForm(data)

    if request.method == "POST" and form.is_valid():
        cita = form.save()
        messages.success(request, "La cita fue creada correctamente.")
        destino = reverse("citas:agenda_citas")
        return redirect(f"{destino}?fecha={cita.fecha:%Y-%m-%d}")

    return render(request, "citas/formulario.html", {
        "form": form,
        "titulo": "Nueva cita",
        "texto_boton": "Guardar cita",
        "bloqueo_agenda": seleccion is not None,
        "seleccion_agenda": token,
        "origen": "agenda",
    })


@login_required
def editar_cita(request, cita_id):
    cita = get_object_or_404(Cita, pk=cita_id)

    origen = request.POST.get(
        "origen",
        request.GET.get("origen", "agenda"),
    )

    if origen not in {"citas", "agenda"}:
        origen = "agenda"

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

            if origen == "citas":
                destino = reverse("citas:listar_citas")
            else:
                destino = reverse("citas:agenda_citas")

            fecha_cita = cita.fecha.strftime("%Y-%m-%d")

            return redirect(f"{destino}?fecha={fecha_cita}")

    else:
        form = CitaForm(instance=cita)

    return render(
        request,
        "citas/formulario.html",
        {
            "form": form,
            "titulo": "Editar cita",
            "texto_boton": "Actualizar cita",
            "origen": origen,
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
                    "Debes seleccionar Prestador de Servicio, "
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