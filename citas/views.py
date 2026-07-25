from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from datetime import datetime

from django.http import JsonResponse

from servicios.models import Servicio

from .disponibilidad import obtener_horas_disponibles

from .forms import CitaForm
from .models import Cita


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
    if request.method == "POST":
        form = CitaForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "La cita fue creada correctamente.",
            )
            return redirect("citas:listar_citas")
    else:
        form = CitaForm()

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
    cita = get_object_or_404(Cita, pk=cita_id)

    if request.method == "POST":
        form = CitaForm(request.POST, instance=cita)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "La cita fue actualizada correctamente.",
            )
            return redirect("citas:listar_citas")
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
    cita = get_object_or_404(Cita, pk=cita_id)

    if request.method == "POST":
        cita.delete()
        messages.success(
            request,
            "La cita fue eliminada correctamente.",
        )
        return redirect("citas:listar_citas")

    return render(
        request,
        "citas/eliminar.html",
        {"cita": cita},
    )


@login_required
def cambiar_estado_cita(request, cita_id):
    cita = get_object_or_404(Cita, pk=cita_id)

    if request.method == "POST":
        nuevo_estado = request.POST.get("estado")
        estados_validos = {
            valor for valor, etiqueta in Cita.Estado.choices
        }

        if nuevo_estado in estados_validos:
            cita.estado = nuevo_estado
            cita.save()

            messages.success(
                request,
                "El estado de la cita fue actualizado.",
            )
        else:
            messages.error(
                request,
                "El estado seleccionado no es válido.",
            )

    return redirect("citas:listar_citas")

@login_required
def consultar_disponibilidad(request):
    barbero_id = request.GET.get("barbero")
    servicio_id = request.GET.get("servicio")
    fecha_texto = request.GET.get("fecha")
    cita_id = request.GET.get("cita")

    if not barbero_id or not servicio_id or not fecha_texto:
        return JsonResponse(
            {
                "horas": [],
                "error": (
                    "Debes seleccionar barbero, "
                    "servicio y fecha."
                ),
            }
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
        servicio = Servicio.objects.get(
            pk=servicio_id,
            activo=True,
        )
    except Servicio.DoesNotExist:
        return JsonResponse(
            {
                "horas": [],
                "error": "El servicio no existe o está inactivo.",
            },
            status=404,
        )

    horas = obtener_horas_disponibles(
        barbero_id=barbero_id,
        servicio=servicio,
        fecha=fecha,
        cita_id=cita_id,
    )

    return JsonResponse(
        {
            "horas": horas,
            "duracion": servicio.duracion,
        }
    )