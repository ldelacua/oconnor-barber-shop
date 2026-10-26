from django import forms
from django.db.models import Q
from .models import GrupoGasto, TipoGasto, Proveedor, RegistroGasto


class EstiloForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for campo in self.fields.values():
            if isinstance(campo.widget,forms.CheckboxInput): clase="form-check-input"
            elif isinstance(campo.widget,forms.Select): clase="form-select"
            else: clase="form-control"
            campo.widget.attrs["class"]=clase
            if isinstance(campo,forms.DecimalField):
                campo.widget.attrs.update({"step":"0.01","min":"0"})
    def clean_descripcion(self):
        return self.cleaned_data["descripcion"].strip()


class GrupoForm(EstiloForm):
    class Meta:
        model=GrupoGasto
        fields=["descripcion","activo"]


class TipoForm(EstiloForm):
    class Meta:
        model=TipoGasto
        fields=["descripcion","grupo","activo"]

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["grupo"].queryset=GrupoGasto.objects.filter(Q(activo=True)|Q(pk=self.instance.grupo_id))

    def clean_grupo(self):
        grupo=self.cleaned_data["grupo"]
        if not grupo.activo and grupo.pk!=self.instance.grupo_id:
            raise forms.ValidationError("Selecciona un grupo activo.")
        return grupo


class ProveedorForm(EstiloForm):
    class Meta:
        model=Proveedor
        fields=["rif","descripcion","activo"]
    def clean_rif(self):
        rif=self.cleaned_data["rif"].strip().upper().replace(" ","")
        if Proveedor.objects.filter(rif__iexact=rif).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un proveedor con este RIF.")
        return rif


class RegistroForm(EstiloForm):
    class Meta:
        model=RegistroGasto
        fields=["fecha_gasto","gasto","proveedor","numero_factura","numero_control","moneda","monto_gasto","monto_impuesto","porcentaje_impuesto"]
        widgets={"fecha_gasto":forms.DateInput(format="%Y-%m-%d",attrs={"type":"date"})}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["gasto"].queryset=TipoGasto.objects.filter(Q(activo=True,grupo__activo=True)|Q(pk=self.instance.gasto_id)).select_related("grupo")
        self.fields["proveedor"].queryset=Proveedor.objects.filter(Q(activo=True)|Q(pk=self.instance.proveedor_id))
        self.fields["monto_gasto"].widget.attrs["min"]="0.01"

    def clean(self):
        datos=super().clean()
        gasto=datos.get("gasto");proveedor=datos.get("proveedor")
        if gasto and (not gasto.activo or not gasto.grupo.activo) and gasto.pk!=self.instance.gasto_id:
            self.add_error("gasto","Selecciona un tipo de gasto y grupo activos.")
        if proveedor and not proveedor.activo and proveedor.pk!=self.instance.proveedor_id:
            self.add_error("proveedor","Selecciona un proveedor activo.")
        factura=datos.get("numero_factura","").strip()
        datos["numero_factura"]=factura
        if proveedor and factura and RegistroGasto.objects.filter(proveedor=proveedor,numero_factura__iexact=factura).exclude(pk=self.instance.pk).exists():
            self.add_error("numero_factura","Ya existe esta factura para el proveedor.")
        return datos


class FiltrosForm(forms.Form):
    desde=forms.DateField(required=False,widget=forms.DateInput(format="%Y-%m-%d",attrs={"type":"date"}))
    hasta=forms.DateField(required=False,widget=forms.DateInput(format="%Y-%m-%d",attrs={"type":"date"}))
    grupo=forms.ModelChoiceField(queryset=GrupoGasto.objects.all(),required=False,empty_label="Todos")
    gasto=forms.ModelChoiceField(queryset=TipoGasto.objects.all(),required=False,empty_label="Todos",label="Tipo de gasto")
    proveedor=forms.ModelChoiceField(queryset=Proveedor.objects.all(),required=False,empty_label="Todos")
    moneda=forms.ChoiceField(required=False,choices=[("","Todas"),("BS","Bs."),("USD","USD")])
    factura=forms.CharField(required=False,max_length=60,label="N.º factura")
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for c in self.fields.values():c.widget.attrs["class"]="form-select" if isinstance(c.widget,forms.Select) else "form-control"
    def clean(self):
        datos=super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"]>datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


from django.forms import inlineformset_factory
from .models import Producto, DetalleRegistroGasto


class ProductoForm(EstiloForm):
    class Meta:
        model = Producto
        fields = [
            "descripcion",
            "unidad_medida",
            "activo",
        ]


class DetalleGastoForm(EstiloForm):
    class Meta:
        model = DetalleRegistroGasto
        fields = ["producto", "cantidad"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto"].queryset = Producto.objects.filter(
            Q(activo=True) | Q(pk=self.instance.producto_id))
        self.fields["cantidad"].widget.attrs.update({"step": "0.001", "min": "0.001"})

    def clean_producto(self):
        producto = self.cleaned_data["producto"]
        if not producto.activo and producto.pk != self.instance.producto_id:
            raise forms.ValidationError("Selecciona un producto activo.")
        return producto


DetalleGastoFormSet = inlineformset_factory(
    RegistroGasto, DetalleRegistroGasto, form=DetalleGastoForm,
    extra=1, can_delete=True, max_num=100, validate_max=True, absolute_max=200,
)
