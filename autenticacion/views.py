from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from django.shortcuts import redirect, render, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.utils import timezone

from clientes.models import Cliente
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
    if request.user.es_prestador_restringido:
        return redirect('mis_citas')
    hoy = timezone.localdate()
    puede_ventas = request.user.has_perm("ventas.view_documentoventa")
    puede_prestadores = request.user.has_perm("barberos.view_barbero")
    ventas_usd = DocumentoVenta.objects.filter(
        fecha=hoy,
        sellado=True,
    ).aggregate(total=Sum("subtotal_usd"))["total"] if puede_ventas else None

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
    )["total"] if puede_ventas else None
    cumpleaneros = Cliente.objects.filter(
        activo=True, dia_nacimiento=hoy.day, mes_nacimiento=hoy.month,
    ).only("id", "nombre", "apellido", "telefono").order_by("nombre", "apellido", "pk") if request.user.has_perm("clientes.view_cliente") else Cliente.objects.none()
    contexto = {
        "cumpleaneros": list(cumpleaneros),
        "hoy": hoy,
        "ventas_dia_usd": ventas_usd if ventas_usd is not None else Decimal("0.00"),
        "total_barberos": Barbero.objects.filter(activo=True).count() if puede_prestadores else None,
        "total_servicios": servicios_dia or 0,
    }
    return render(request, "autenticacion/dashboard.html", contexto)


def _prestador_propio(request):
    if not request.user.es_prestador_restringido or not request.user.prestador_id:
        raise PermissionDenied('Tu cuenta no tiene un prestador asociado. Contacta al administrador.')
    return request.user.prestador_id


@login_required
def mis_citas(request):
    from citas.models import Cita
    prestador_id = _prestador_propio(request)
    citas = Cita.objects.filter(barbero_id=prestador_id).select_related('cliente', 'servicio').prefetch_related('servicios').order_by('-fecha', '-hora')
    return render(request, 'autenticacion/mis_citas.html', {'pagina': Paginator(citas, 30).get_page(request.GET.get('page'))})


@login_required
def mis_liquidaciones(request):
    from liquidaciones.models import Liquidacion
    prestador_id = _prestador_propio(request)
    liquidaciones = Liquidacion.objects.filter(prestador_id=prestador_id, sellado=True)
    return render(request, 'autenticacion/mis_liquidaciones.html', {'pagina': Paginator(liquidaciones, 30).get_page(request.GET.get('page'))})


@login_required
def mi_liquidacion(request, pk):
    from liquidaciones.models import Liquidacion
    prestador_id = _prestador_propio(request)
    documento = get_object_or_404(Liquidacion.objects.prefetch_related('detalles__detalle_venta__documento','detalles__ajuste_de__liquidacion','pagos'), pk=pk, prestador_id=prestador_id, sellado=True)
    return render(request, 'liquidaciones/documento.html', {'documento': documento})


def cerrar_sesion(request):
    logout(request)
    return redirect("iniciar_sesion")
