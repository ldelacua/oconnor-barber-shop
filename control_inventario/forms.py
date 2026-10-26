import uuid
from django import forms
from django.utils import timezone
from django.forms import formset_factory
from django.urls import reverse
from inventario.models import Producto
from inventario.precision import configurar_decimales
from inventario.buscador_productos import BuscadorProductoWidget
from decimal import Decimal

class BuscadorAjusteWidget(BuscadorProductoWidget):
    def get_context(self,*args,**kwargs):
        contexto=super().get_context(*args,**kwargs)
        contexto["widget"]["url"]=reverse("control_inventario:buscar")
        return contexto

class AjusteForm(forms.Form):
    tipo=forms.ChoiceField(choices=[("EN","Entrada (+)"),("SA","Salida (-)")])
    fecha=forms.DateField(initial=timezone.localdate,widget=forms.DateInput(format="%Y-%m-%d",attrs={"type":"date"}))
    observacion=forms.CharField(label="Motivo / Observación",max_length=2000,widget=forms.Textarea(attrs={"rows":2,"data-mayusculas":"1"}))
    clave=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for campo in self.fields.values():campo.widget.attrs["class"]="form-control"

class LineaAjusteForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        configurar_decimales(self)
    producto=forms.ModelChoiceField(Producto.objects.all(),widget=BuscadorAjusteWidget)
    cantidad=forms.DecimalField(max_digits=14,decimal_places=2,min_value=Decimal(".01"),
        widget=forms.NumberInput(attrs={"class":"form-control","step":".01","min":".01"}))

LineasAjuste=formset_factory(LineaAjusteForm,extra=1,min_num=1,validate_min=True,
    can_delete=True,max_num=100,validate_max=True,absolute_max=100)

class PeriodoForm(forms.Form):
    periodo=forms.DateField(input_formats=["%Y-%m"],initial=lambda:timezone.localdate().replace(day=1),
        widget=forms.DateInput(format="%Y-%m",attrs={"type":"month","class":"form-control"}))
    q=forms.CharField(required=False,max_length=100,label="Código o descripción",
        widget=forms.TextInput(attrs={"class":"form-control"}))

class InicioCierreForm(forms.Form):
    periodo=forms.DateField(input_formats=["%Y-%m"],label="Mes a cerrar",
        widget=forms.DateInput(format="%Y-%m",attrs={"type":"month","class":"form-control"}))
    observacion=forms.CharField(required=False,max_length=2000,
        widget=forms.Textarea(attrs={"class":"form-control","rows":2,"data-mayusculas":"1"}))

class ConteoForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        configurar_decimales(self)
    renglon=forms.IntegerField(widget=forms.HiddenInput)
    fisico=forms.DecimalField(max_digits=14,decimal_places=2,min_value=0,
        widget=forms.NumberInput(attrs={"class":"form-control","min":"0","step":".01","aria-label":"Cantidad física"}))

ConteoFormSet=formset_factory(ConteoForm,extra=0,max_num=25,validate_max=True,absolute_max=25)
