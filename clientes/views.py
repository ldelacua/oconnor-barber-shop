from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ClienteForm
from .models import Cliente


@login_required
def lista_clientes(request):
    busqueda = request.GET.get("q", "").strip()

    clientes = Cliente.objects.all()

    if busqueda:
        clientes = clientes.filter(
            Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(telefono__icontains=busqueda)
            | Q(email__icontains=busqueda)
        )

    clientes = clientes.order_by("nombre", "apellido")

    paginador = Paginator(clientes, 10)
    numero_pagina = request.GET.get("page")
    pagina_clientes = paginador.get_page(numero_pagina)

    return render(
        request,
        "clientes/lista.html",
        {
            "clientes": pagina_clientes,
            "busqueda": busqueda,
        },
    )


@login_required
def crear_cliente(request):
    if request.method == "POST":
        formulario = ClienteForm(request.POST)

        if formulario.is_valid():
            formulario.save()
            return redirect("lista_clientes")
    else:
        formulario = ClienteForm()

    return render(
        request,
        "clientes/formulario.html",
        {"formulario": formulario},
    )


@login_required
def editar_cliente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    if request.method == "POST":
        formulario = ClienteForm(
            request.POST,
            instance=cliente,
        )

        if formulario.is_valid():
            formulario.save()
            return redirect("lista_clientes")
    else:
        formulario = ClienteForm(instance=cliente)

    return render(
        request,
        "clientes/formulario.html",
        {
            "formulario": formulario,
            "cliente": cliente,
            "editar": True,
        },
    )