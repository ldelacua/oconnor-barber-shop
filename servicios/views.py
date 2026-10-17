from django.db.models.deletion import ProtectedError
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ServicioForm
from .models import Servicio


def lista_servicios(request):
    servicios = Servicio.objects.all()

    contexto = {
        "servicios": servicios,
    }

    return render(
        request,
        "servicios/lista.html",
        contexto,
    )


def crear_servicio(request):
    if request.method == "POST":
        form = ServicioForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "El servicio fue creado correctamente.",
            )
            return redirect("servicios:lista")
    else:
        form = ServicioForm()

    contexto = {
        "form": form,
        "titulo": "Nuevo servicio",
    }

    return render(
        request,
        "servicios/formulario.html",
        contexto,
    )


def editar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk)

    if request.method == "POST":
        form = ServicioForm(
            request.POST,
            instance=servicio,
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "El servicio fue actualizado correctamente.",
            )
            return redirect("servicios:lista")
    else:
        form = ServicioForm(instance=servicio)

    contexto = {
        "form": form,
        "servicio": servicio,
        "titulo": "Editar servicio",
    }

    return render(
        request,
        "servicios/formulario.html",
        contexto,
    )


def eliminar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk)

    tiene_citas = (
        servicio.citas.exists()
        or servicio.citas_multiples.exists()
    )

    if tiene_citas:
        messages.warning(
            request,
            "No puedes eliminar este servicio porque tiene "
            "citas asociadas. Puedes desactivarlo para "
            "conservar el historial.",
        )
        return redirect("servicios:lista")

    if request.method == "POST":
        try:
            servicio.delete()
        except ProtectedError:
            messages.warning(
                request,
                "No puedes eliminar este servicio porque "
                "tiene registros asociados.",
            )
        else:
            messages.success(
                request,
                "El servicio fue eliminado correctamente.",
            )

        return redirect("servicios:lista")

    return render(
        request,
        "servicios/eliminar.html",
        {"servicio": servicio},
    )        
    return redirect("servicios:lista")

    contexto = {
        "servicio": servicio,
    }

    return render(
        request,
        "servicios/eliminar.html",
        contexto,
    )