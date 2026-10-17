import uuid
from decimal import Decimal
from django import forms
from django.forms import formset_factory
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from citas.buscador_clientes import BuscadorClienteWidget


class VentaForm(forms.Form):
    fecha = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}))
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.filter(activo=True), widget=BuscadorClienteWidget())
    clave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class PrestadorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, prestador):
        return f"{prestador.nombre} {prestador.apellido}"


class ServicioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, servicio):
        return servicio.nombre


class LineaForm(forms.Form):
    barbero = PrestadorChoiceField(
        queryset=Barbero.objects.filter(activo=True),
        label="Prestador de servicio",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    servicio = ServicioChoiceField(queryset=Servicio.objects.filter(activo=True), widget=forms.Select(attrs={"class": "form-select servicio-venta"}))
    cantidad_servicio = forms.IntegerField(label="Cantidad", min_value=1, max_value=10000, initial=1, widget=forms.NumberInput(attrs={"class": "form-control cantidad-venta", "min": 1}))


LineasFormSet = formset_factory(LineaForm, extra=1, min_num=1, validate_min=True, max_num=50, validate_max=True, absolute_max=60, can_delete=True)


class ReversoForm(forms.Form):
    motivo = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}), label="Motivo del reverso")


class FiltrosForm(forms.Form):
    numero = forms.IntegerField(required=False, min_value=1, label="N.º documento")
    tipo = forms.ChoiceField(required=False, choices=[("", "Todos"), ("FA", "FA"), ("RE", "RE")])
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    cliente = forms.CharField(required=False, max_length=100, label="Nombre del cliente")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class PagoForm(forms.Form):
    tipo_pago = forms.ChoiceField(label="Forma de pago", widget=forms.Select(attrs={"class": "form-select tipo-pago"}))
    fecha = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}))
    referencia = forms.CharField(required=False, max_length=100, label="Referencia", widget=forms.TextInput(attrs={"class": "form-control"}))
    observacion = forms.CharField(required=False, max_length=500, label="Observación", widget=forms.TextInput(attrs={"class": "form-control"}))
    monto = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"), widget=forms.NumberInput(attrs={"class": "form-control monto-pago", "min": "0.01", "step": "0.01"}))

    def __init__(self, *args, catalogo=None, **kwargs):
        super().__init__(*args, **kwargs)
        catalogo = catalogo or {}
        self.fields["tipo_pago"].choices = [("", "Seleccione")] + [
            (str(codigo), f'{tipo["nombre"]} ({tipo["moneda"]})')
            for codigo, tipo in catalogo.items()
        ]


PagosFormSet = formset_factory(PagoForm, extra=0, min_num=1, validate_min=True, max_num=20, validate_max=True, absolute_max=25, can_delete=True)
