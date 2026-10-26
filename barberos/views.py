from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import BarberoForm
from .models import Barbero


@login_required
def lista_barberos(request):
    busqueda = request.GET.get("buscar", "").strip()

    barberos = Barbero.objects.select_related("silla").all()

    if busqueda:
        barberos = barberos.filter(
            Q(codigo__icontains=busqueda)
            | Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(telefono__icontains=busqueda)
            | Q(correo__icontains=busqueda)
            | Q(codigo_silla__icontains=busqueda)
            | Q(silla__nombre__icontains=busqueda)
        )

    paginador = Paginator(barberos, 10)
    numero_pagina = request.GET.get("page")
    pagina_barberos = paginador.get_page(numero_pagina)

    contexto = {
        "barberos": pagina_barberos,
        "busqueda": busqueda,
    }

    return render(request, "barberos/lista.html", contexto)


@login_required
def crear_barbero(request):
    if request.method == "POST":
        formulario = BarberoForm(request.POST)

        if formulario.is_valid():
            formulario.save()

            messages.success(
                request,
                "El prestador de servicio fue registrado correctamente.",
            )

            return redirect("barberos:lista_barberos")
    else:
        formulario = BarberoForm()

    contexto = {
        "formulario": formulario,
        "titulo": "Nuevo Prest Servicio",
        "descripcion": "Registra la información del Prestador de Servicio.",
        "texto_boton": "Guardar Prest Servicio",
    }

    return render(
        request,
        "barberos/formulario.html",
        contexto,
    )


@login_required
def editar_barbero(request, pk):
    barbero = get_object_or_404(Barbero, pk=pk)

    if request.method == "POST":
        formulario = BarberoForm(
            request.POST,
            instance=barbero,
        )

        if formulario.is_valid():
            formulario.save()

            messages.success(
                request,
                "La información del prestador de servicio fue actualizada correctamente.",
            )

            return redirect("barberos:lista_barberos")
    else:
        formulario = BarberoForm(instance=barbero)

    contexto = {
        "formulario": formulario,
        "barbero": barbero,
        "titulo": "Editar prestador de servicio",
        "descripcion": "Actualiza la información del prestador de servicio.",
        "texto_boton": "Guardar cambios",
    }

    return render(
        request,
        "barberos/formulario.html",
        contexto,
    )


@login_required
def detalle_barbero(request, pk):
    barbero = get_object_or_404(Barbero, pk=pk)

    contexto = {
        "barbero": barbero,
    }

    return render(
        request,
        "barberos/detalle.html",
        contexto,
    )