from datetime import datetime
from hashlib import sha256

from django import forms
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from barberos.models import Barbero
from citas.forms import CitaForm, ServiciosMultipleChoiceField
from mysql_nuevo.bloqueos import mutacion_mysql
from .models import Cliente, validar_telefono


class Acceso(forms.Form):
    telefono = forms.CharField(label="Teléfono (11 dígitos)", validators=[validar_telefono], max_length=11)
    clave = forms.CharField(label="Contraseña", max_length=128, strip=False,
                            widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class Registro(Acceso):
    nombre = forms.CharField(max_length=100)
    apellido = forms.CharField(max_length=100)
    email = forms.EmailField(label="Correo electrónico", max_length=254)
    clave = forms.CharField(label="Contraseña", max_length=128, strip=False,
                            widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    field_order = ["nombre", "apellido", "email", "telefono", "clave"]

    def clean_clave(self):
        clave = self.cleaned_data["clave"]
        validate_password(clave)
        if len(clave) < 8:
            raise forms.ValidationError("Usa al menos 8 caracteres.")
        return clave


def iniciar(request, cliente):
    request.session.cycle_key()
    request.session["portal_cliente"] = cliente.pk
    request.session["portal_acceso"] = int(timezone.now().timestamp())
    return redirect("portal_citas")


def limite(request):
    ip = request.META.get("REMOTE_ADDR", "")
    clave = "portal:intentos:" + sha256(ip.encode()).hexdigest()
    if cache.add(clave, 1, timeout=300):
        return False
    try:
        return cache.incr(clave) > 20
    except ValueError:
        return False


@never_cache
@require_http_methods(["GET", "POST"])
def acceso(request, registro=False):
    form = (Registro if registro else Acceso)(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if limite(request):
            return render(request, "clientes/portal.html", {"aviso": "Demasiados intentos. Intenta de nuevo en cinco minutos."}, status=429)
        if form.is_valid():
            datos = form.cleaned_data.copy()
            clave = datos.pop("clave")
            if registro:
                try:
                    with transaction.atomic():
                        cliente = Cliente.objects.create(**datos, clave_portal=make_password(clave))
                except IntegrityError:
                    if not Cliente.objects.filter(telefono=datos["telefono"]).exists():
                        raise
                    form.add_error("telefono", "Este teléfono ya está registrado. Inicia sesión o contacta a la barbería.")
                else:
                    return iniciar(request, cliente)
            else:
                cliente = Cliente.objects.filter(telefono=datos["telefono"], activo=True).first()
                if cliente and cliente.clave_portal:
                    if check_password(clave, cliente.clave_portal):
                        return iniciar(request, cliente)
                else:
                    make_password(clave)  # Coste comparable si no existe una contraseña.
                form.add_error(None, "Teléfono o contraseña incorrectos. Si ya eras cliente y no tienes contraseña, contacta a la barbería.")
    return render(request, "clientes/portal.html", {"form": form, "modo": "registro" if registro else "acceso"})


@never_cache
def confirmar(request, token):
    return redirect("portal_acceso")


class ServiciosPortal(ServiciosMultipleChoiceField):
    def label_from_instance(self, servicio):
        return f"{servicio.nombre} · ${servicio.precio:.2f}"


class Reserva(CitaForm):
    servicios = ServiciosPortal(
        queryset=CitaForm.base_fields["servicios"].queryset,
        label="Servicios",
        widget=forms.CheckboxSelectMultiple,
        help_text="Selecciona uno o varios servicios para esta cita.",
    )

    class Meta(CitaForm.Meta):
        fields = ("barbero", "servicios", "fecha", "hora")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["barbero"].queryset = Barbero.objects.filter(activo=True)


@never_cache
@require_http_methods(["GET", "POST"])
@mutacion_mysql
def citas(request):
    cliente = Cliente.objects.filter(pk=request.session.get("portal_cliente"), activo=True).first()
    if not cliente or int(timezone.now().timestamp()) - request.session.get("portal_acceso", 0) > 3600:
        return redirect("portal_acceso")
    if request.method == "POST" and "salir" in request.POST:
        for clave in ("portal_cliente", "portal_acceso"):
            request.session.pop(clave, None)
        return redirect("/")
    form = Reserva(request.POST if request.method == "POST" else None)
    if request.method == "POST" and request.POST.get("accion") == "reservar" and form.is_valid():
        cita = form.save(commit=False)
        cita.cliente = cliente
        inicio = timezone.make_aware(datetime.combine(cita.fecha, cita.hora))
        if inicio <= timezone.now():
            form.add_error("hora", "Elige una hora futura.")
        else:
            try:
                with transaction.atomic():
                    cita.save()
                    form.save_m2m()
                return redirect("portal_citas")
            except IntegrityError:
                form.add_error("hora", "La hora dejó de estar disponible. Consulta otra.")
    elif request.method == "POST" and request.POST.get("accion") == "horas":
        form.errors  # Valida los datos usados para calcular disponibilidad.
        if form.errors.get("hora") and not request.POST.get("hora"):
            form.errors.pop("hora", None)
    from ventas.fidelidad import tarjetas
    return render(request, "clientes/portal.html", {"tarjetas": tarjetas(cliente), "form": form, "modo": "citas", "citas": cliente.citas.select_related("barbero").prefetch_related("servicios").order_by("-fecha", "-hora")[:50]})
