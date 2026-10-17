from decimal import Decimal

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render

from .models import PagoVenta
from .pagos_calculos import leer_tipos_pago


class FiltrosPagosForm(forms.Form):
    desde = forms.DateField(required=False, label="Pago desde", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    hasta = forms.DateField(required=False, label="Pago hasta", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    numero = forms.IntegerField(required=False, min_value=1, label="N.º documento")
    tipo = forms.ChoiceField(required=False, label="Tipo de documento", choices=[("", "FA y RE"), ("FA", "FA"), ("RE", "RE")])
    cliente = forms.CharField(required=False, max_length=100, label="Cliente")
    forma_pago = forms.ChoiceField(required=False, label="Forma de pago")
    moneda = forms.ChoiceField(required=False, choices=[("", "Todas"), ("USD", "USD"), ("BS", "Bs.")])
    referencia = forms.CharField(required=False, max_length=100, label="Referencia")

    def __init__(self, *args, opciones_pago=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forma_pago"].choices = [("", "Todas")] + list(opciones_pago)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


@login_required
def consulta_pagos(request):
    # Se incluyen los tipos históricos aunque ya no estuvieran en el JSON.
    nombres = {}
    for codigo, nombre in PagoVenta.objects.filter(documento__sellado=True).order_by("tipo_pago", "nombre_tipo_pago").values_list("tipo_pago", "nombre_tipo_pago").distinct():
        nombres[codigo] = nombre
    try:
        nombres.update({codigo: tipo["nombre"] for codigo, tipo in leer_tipos_pago().items()})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    opciones = [(str(codigo), nombre) for codigo, nombre in sorted(nombres.items())]
    filtros = FiltrosPagosForm(request.GET, opciones_pago=opciones)
    pagos = PagoVenta.objects.filter(documento__sellado=True).select_related("documento__cliente").order_by("-fecha", "-documento_id", "-pk")
    if filtros.is_valid():
        datos = filtros.cleaned_data
        if datos.get("desde"):
            pagos = pagos.filter(fecha__gte=datos["desde"])
        if datos.get("hasta"):
            pagos = pagos.filter(fecha__lte=datos["hasta"])
        if datos.get("numero"):
            pagos = pagos.filter(documento_id=datos["numero"])
        if datos.get("tipo"):
            pagos = pagos.filter(documento__tipo_documento=datos["tipo"])
        if datos.get("forma_pago"):
            pagos = pagos.filter(tipo_pago=int(datos["forma_pago"]))
        if datos.get("moneda"):
            pagos = pagos.filter(moneda=datos["moneda"])
        if datos.get("referencia"):
            pagos = pagos.filter(referencia__icontains=datos["referencia"])
        for palabra in datos.get("cliente", "").split():
            pagos = pagos.filter(Q(documento__cliente__nombre__icontains=palabra) | Q(documento__cliente__apellido__icontains=palabra))
    else:
        pagos = pagos.none()
    # Agregar ANTES de paginar: totales de todos los resultados de la consulta.
    totales = pagos.aggregate(
        usd=Sum("monto", filter=Q(moneda="USD")),
        bs=Sum("monto", filter=Q(moneda="BS")),
    )
    totales = {moneda: valor if valor is not None else Decimal("0.00") for moneda, valor in totales.items()}
    pagina = Paginator(pagos, 30).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ventas/consulta_pagos.html", {
        "filtros": filtros, "pagina": pagina, "totales": totales,
        "parametros": parametros.urlencode(),
    })
