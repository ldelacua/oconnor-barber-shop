from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from barberos.models import Barbero
from ventas_productos.forms import LineaForm
from ventas_productos.servicios import calcular_productos
from .models import CobroCompartido


class VendedorForm(forms.Form):
    prestador = forms.ModelChoiceField(Barbero.objects.filter(activo=True), required=False,
        empty_label="Barbería", label="Venta realizada por", widget=forms.Select(attrs={"class": "form-select"}))


LineasProductos = forms.formset_factory(LineaForm, extra=1, max_num=50, absolute_max=50,
                                        validate_max=True, can_delete=True)
PERMISOS_VENTA = ("ventas.add_documentoventa", "ventas_productos.add_documentoproducto")


def habilitado(usuario):
    return getattr(settings, "VENTA_COMBINADA", False) and usuario.has_perms(PERMISOS_VENTA)


def filas_productos(formset):
    return [f.cleaned_data for f in formset if f.cleaned_data and not f.cleaned_data.get("DELETE")]


@login_required
@permission_required(PERMISOS_VENTA, raise_exception=True)
@require_POST
def cotizar(request):
    if not habilitado(request.user):
        raise PermissionDenied
    lineas = LineasProductos(request.POST, prefix="productos")
    if not lineas.is_valid():
        return JsonResponse({"error": "Revisa los productos y sus cantidades."}, status=400)
    filas = filas_productos(lineas)
    if not filas:
        return JsonResponse({"total": "0.00"})
    try:
        _, _, preparadas, *_, total = calcular_productos(timezone.localdate(), filas, usuario=request.user)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return JsonResponse({"total": str(total), "renglones": {
        p["producto"].pk: {
            "precio": str(p["precio_unitario_usd"]),
            "neto": str(p["subtotal_usd"] - p["descuento_usd"]),
            "promocion": p["promocion"],
        } for p in preparadas
    }})


@login_required
@permission_required(("ventas.view_documentoventa", "ventas_productos.view_documentoproducto"), raise_exception=True)
@require_GET
def ver(request, pk):
    cobro = get_object_or_404(CobroCompartido.objects.select_related("servicios", "productos", "cuenta__banco"), pk=pk)
    return render(request, "ventas/cobro_compartido.html", {"cobro": cobro, "seccion_pagos": request.GET.get("desde_pagos") == "1"})
