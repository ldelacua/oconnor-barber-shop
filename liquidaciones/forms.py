from django import forms
from django.utils import timezone
from barberos.models import Barbero


class PrestadorField(forms.ModelChoiceField):
    def label_from_instance(self, objeto):
        return f"{objeto.nombre} {objeto.apellido}"


class CabeceraForm(forms.Form):
    prestador = PrestadorField(queryset=Barbero.objects.all(), label="Prestador de Servicio")
    desde = forms.DateField(initial=lambda: timezone.localdate().replace(day=1), label="Servicios desde", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    hasta = forms.DateField(initial=timezone.localdate, label="Servicios hasta", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    fecha_cancelacion = forms.DateField(initial=timezone.localdate, label="Fecha de cancelación", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, forms.Select) else "form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("El inicio del período no puede ser posterior al final.")
        if datos.get("hasta") and datos.get("fecha_cancelacion") and datos["hasta"] > datos["fecha_cancelacion"]:
            raise forms.ValidationError("El período no puede terminar después de la fecha de cancelación.")
        return datos


class FiltrosLista(forms.Form):
    numero = forms.IntegerField(required=False, min_value=1, label="N.º cancelación")
    prestador = PrestadorField(queryset=Barbero.objects.all(), required=False, empty_label="Todos", label="Prestador")
    desde = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget,forms.Select) else "form-control"

    def clean(self):
        datos=super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"]>datos["hasta"]:
            raise forms.ValidationError("El inicio no puede ser posterior al final.")
        return datos
