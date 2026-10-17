from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from barberos.models import Barbero
from .models import DetalleVenta
from .resumen_servicios import agrupar_detalles


class PrestadorReporteField(forms.ModelChoiceField):
    def label_from_instance(self, prestador):
        return f"{prestador.nombre} {prestador.apellido}"


class FiltrosServiciosForm(forms.Form):
    tipo = forms.ChoiceField(
        required=False, label="Tipo de documento",
        choices=[("", "FA y RE"), ("FA", "FA"), ("RE", "RE")],
    )
    desde = forms.DateField(
        required=False, label="Desde",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    hasta = forms.DateField(
        required=False, label="Hasta",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    prestador = PrestadorReporteField(
        queryset=Barbero.objects.all().order_by("nombre", "apellido", "pk"),
        required=False, empty_label="Todos", label="Prestador de Servicio",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


@login_required
def reporte_servicios(request):
    filtros = FiltrosServiciosForm(request.GET)
    detalles = DetalleVenta.objects.filter(
        documento__sellado=True,
    ).select_related("documento", "barbero").order_by(
        "documento__fecha", "documento_id", "pk",
    )
    valido = filtros.is_valid()
    if valido:
        datos = filtros.cleaned_data
        if datos.get("tipo"):
            detalles = detalles.filter(documento__tipo_documento=datos["tipo"])
        if datos.get("desde"):
            detalles = detalles.filter(documento__fecha__gte=datos["desde"])
        if datos.get("hasta"):
            detalles = detalles.filter(documento__fecha__lte=datos["hasta"])
        if datos.get("prestador"):
            detalles = detalles.filter(barbero_id=datos["prestador"].pk)
    else:
        detalles = detalles.none()
    grupos, total = agrupar_detalles(detalles)
    seleccion = []
    for campo in filtros:
        if not campo.value():
            continue
        valor = campo.value()
        if campo.name == "prestador":
            prestador = filtros.cleaned_data.get("prestador")
            if prestador:
                valor = f"{prestador.nombre} {prestador.apellido}"
        seleccion.append({"etiqueta": campo.label, "valor": valor})
    return render(request, "ventas/reporte_servicios.html", {
        "filtros": filtros, "grupos": grupos, "total": total,
        "seleccion": seleccion, "generado_en": timezone.localtime(),
        "filtros_validos": valido,
    })
