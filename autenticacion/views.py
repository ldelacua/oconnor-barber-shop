from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render

from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio


def iniciar_sesion(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        usuario = authenticate(
            request,
            username=username,
            password=password,
        )

        if usuario is not None:
            login(request, usuario)

            siguiente = request.POST.get("next") or request.GET.get("next")

            if siguiente:
                return redirect(siguiente)

            return redirect("dashboard")

        return render(
            request,
            "autenticacion/login.html",
            {
                "error": "Usuario o contraseña incorrectos.",
                "next": request.GET.get("next", ""),
            },
        )

    return render(
        request,
        "autenticacion/login.html",
        {"next": request.GET.get("next", "")},
    )


@login_required
def dashboard(request):
    contexto = {
        "total_clientes": Cliente.objects.filter(activo=True).count(),
        "total_barberos": Barbero.objects.filter(activo=True).count(),
        "total_servicios": Servicio.objects.filter(activo=True).count(),
    }

    return render(
        request,
        "autenticacion/dashboard.html",
        contexto,
    )


def cerrar_sesion(request):
    logout(request)
    return redirect("iniciar_sesion")