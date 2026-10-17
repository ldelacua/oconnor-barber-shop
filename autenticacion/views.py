from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from barberos.models import Barbero
from servicios.models import Servicio
from ventas.models import DocumentoVenta, DetalleVenta
from django.db.models import Case, When, F, IntegerField

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
    hoy = timezone.localdate()
    ventas_usd = DocumentoVenta.objects.filter(
        fecha=hoy,
        sellado=True,
    ).aggregate(total=Sum("subtotal_usd"))["total"]

    servicios_dia = DetalleVenta.objects.filter(
        documento__fecha=hoy,
        documento__sellado=True,
    ).aggregate(
        total=Sum(
            Case(
                When(
                    documento__tipo_documento="RE",
                    then=-F("cantidad_servicio"),
                ),
                default=F("cantidad_servicio"),
                output_field=IntegerField(),
            )
        )
    )["total"]
    contexto = {
        "hoy": hoy,
        "ventas_dia_usd": ventas_usd if ventas_usd is not None else Decimal("0.00"),
        "total_barberos": Barbero.objects.filter(activo=True).count(),
        "total_servicios": servicios_dia or 0,
    }
    return render(request, "autenticacion/dashboard.html", contexto)


def cerrar_sesion(request):
    logout(request)
    return redirect("iniciar_sesion")
