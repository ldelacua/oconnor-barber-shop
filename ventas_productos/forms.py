import uuid
from decimal import Decimal
from django import forms
from django.forms import formset_factory
from django.utils import timezone
from clientes.models import Cliente
from inventario.models import Producto
from .models import PorcentajeProducto,EscalaDescuento
from inventario.precision import configurar_decimales
from inventario.buscador_productos import BuscadorProductoWidget
from citas.buscador_clientes import BuscadorClienteWidget
from ventas.forms import PagoForm

class CabeceraForm(forms.Form):
    fecha = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type":"date","class":"form-control"}))
    cliente = forms.ModelChoiceField(Cliente.objects.filter(activo=True), widget=BuscadorClienteWidget())
    observacion = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"rows":2,"class":"form-control","data-mayusculas":"1"}))
    clave = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())

    def clean_observacion(self):
        return self.cleaned_data["observacion"].upper()

class LineaForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        configurar_decimales(self)
    producto = forms.ModelChoiceField(Producto.objects.filter(activo=True), widget=BuscadorProductoWidget())
    cantidad = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"),
        initial=1, widget=forms.NumberInput(attrs={"class":"form-control","min":"0.01","step":"0.01"}))

LineasFormSet = formset_factory(LineaForm, extra=1, min_num=1, validate_min=True, can_delete=True,
                                max_num=50, absolute_max=50, validate_max=True)
PagosFormSet = formset_factory(PagoForm, extra=1, min_num=0, validate_min=True, can_delete=True,
                               max_num=20, absolute_max=20, validate_max=True)

class ReversoForm(forms.Form):
    motivo = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"class":"form-control","rows":3,"data-mayusculas":"1"}))

    def clean_motivo(self):
        return self.cleaned_data["motivo"].upper()

class FiltroForm(forms.Form):
    numero = forms.IntegerField(required=False, min_value=1, label="Documento")
    tipo = forms.ChoiceField(required=False, choices=[("","Todos"),("VP","Ventas"),("RP","Reversos")])
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type":"date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type":"date"}))
    cliente = forms.CharField(required=False, max_length=100)
    producto = forms.CharField(required=False, max_length=100, label="Código o nombre del producto")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values(): campo.widget.attrs["class"]="form-control"

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha desde debe ser anterior o igual a la fecha hasta.")
        return datos


class PorcentajeForm(forms.ModelForm):
    porcentaje=forms.DecimalField(label="Recargo sobre costo (%)",max_digits=7,decimal_places=2,min_value=0)
    class Meta:
        model=PorcentajeProducto
        fields=["producto","porcentaje","activo"]
        widgets={"producto":BuscadorProductoWidget()}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        configurar_decimales(self)
        for campo in self.fields.values():
            campo.widget.attrs["class"]="form-check-input" if isinstance(campo.widget,forms.CheckboxInput) else "form-control"
        if self.instance.pk:
            self.fields["producto"].disabled=True

class EscalaForm(forms.ModelForm):
    unidades_mayor_que=forms.DecimalField(label="Desde X unidades (mayor o igual)",max_digits=14,decimal_places=2,min_value=0)
    porcentaje=forms.DecimalField(label="Descuento (%)",max_digits=5,decimal_places=2,min_value=0,max_value=100)
    class Meta:
        model=EscalaDescuento
        fields=["nivel","unidades_mayor_que","porcentaje","activo"]
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        configurar_decimales(self)
        for campo in self.fields.values():campo.widget.attrs["class"]="form-check-input" if isinstance(campo.widget,forms.CheckboxInput) else "form-control"
        if self.instance.pk:self.fields["nivel"].disabled=True
