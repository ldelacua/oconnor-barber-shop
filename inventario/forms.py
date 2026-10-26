from decimal import Decimal, localcontext
from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.db.models import Q
from .models import Producto, Proveedor, Compra, DetalleCompra, UnidadMedida
from .condiciones import iva_vigente, tasa_para_fecha
from .buscador_productos import BuscadorProductoWidget
from .precision import configurar_decimales
from django.core.exceptions import ValidationError

class EstiloForm(forms.ModelForm):
    def clean(self):
        datos = super().clean()
        for nombre, valor in datos.items():
            if isinstance(valor, str) and isinstance(self.fields[nombre], forms.CharField):
                datos[nombre] = valor.upper()
        return datos

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configurar_decimales(self)
        for campo in self.fields.values():
            if isinstance(campo, forms.CharField) and not isinstance(campo.widget, forms.HiddenInput):
                campo.widget.attrs["data-mayusculas"] = "1"
                campo.widget.attrs["style"] = "text-transform: uppercase"
            campo.widget.attrs["class"] = ("form-check-input" if isinstance(campo.widget, forms.CheckboxInput)
                else "form-select" if isinstance(campo.widget, forms.Select) else "form-control")

class UnidadMedidaForm(EstiloForm):
    class Meta:
        model = UnidadMedida
        fields = ["codigo", "nombre", "activo"]

class ProductoForm(EstiloForm):
    volumen = forms.DecimalField(label="Volumen", max_digits=14, decimal_places=2,
                                min_value=Decimal("0.01"))
    unidad_medida = forms.ModelChoiceField(UnidadMedida.objects.none(), label="Unidad de medida")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unidad_medida"].queryset = UnidadMedida.objects.filter(
            Q(activo=True) | Q(pk=self.instance.unidad_medida_id))

    class Meta:
        model = Producto
        fields = ["codigo_producto", "nombre_producto", "volumen", "unidad_medida", "observacion", "activo"]
        widgets = {"observacion": forms.Textarea(attrs={"rows": 3})}

class ProveedorForm(EstiloForm):
    class Meta:
        model = Proveedor
        fields = ["nombre", "direccion", "rif", "telefono", "activo"]

_AUTOMATICO = object()

class CompraForm(EstiloForm):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=0, initial=0)
    class Meta:
        model = Compra
        fields = ["proveedor", "numero_factura", "numero_control", "fecha_compra",
                  "divisa", "observacion"]
        widgets = {"fecha_compra": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "observacion": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].queryset = Proveedor.objects.filter(
            Q(activo=True) | Q(pk=self.instance.proveedor_id))
        self.fields["version"].initial = self.instance.revision
        try:
            self.iva_automatico = iva_vigente()
            self.error_configuracion = ""
        except ValidationError as exc:
            self.iva_automatico = None
            self.error_configuracion = " ".join(exc.messages)

    @property
    def fecha_consulta(self):
        try:
            return self.fields["fecha_compra"].clean(self.data.get("fecha_compra") if self.is_bound else
                                                     self.initial.get("fecha_compra", self.instance.fecha_compra))
        except forms.ValidationError:
            return None

    @property
    def tasa_informativa(self):
        try:
            return tasa_para_fecha(self.fecha_consulta) if self.fecha_consulta else None
        except ValidationError:
            return None

    def clean(self):
        datos = super().clean()
        try:
            if self.error_configuracion:
                raise ValidationError(self.error_configuracion)
            if datos.get("fecha_compra"):
                self.instance.tasa_cambio = tasa_para_fecha(datos["fecha_compra"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return datos

    def clean_numero_factura(self):
        return self.cleaned_data["numero_factura"].strip().upper()

class DetalleForm(EstiloForm):
    cantidad=forms.DecimalField(max_digits=14,decimal_places=2,min_value=Decimal("0.01"))
    precio_unitario=forms.DecimalField(label="Precio Unitario",max_digits=18,decimal_places=2,min_value=Decimal("0.01"))
    class Meta:
        model = DetalleCompra
        fields = ["producto", "cantidad", "precio_unitario"]
        widgets = {"producto": BuscadorProductoWidget()}

    def __init__(self, *args, iva=_AUTOMATICO, **kwargs):
        super().__init__(*args, **kwargs)
        if iva is _AUTOMATICO:
            try:
                iva = iva_vigente()
            except ValidationError:
                iva = None
        self.iva_automatico = iva
        self.fields["producto"].queryset = Producto.objects.filter(
            Q(activo=True) | Q(pk=self.instance.producto_id))

    def clean(self):
        datos = super().clean()
        if self.iva_automatico is None:
            raise forms.ValidationError("No se pudo obtener el IVA del sistema.")
        self.instance.tasa_impuesto = self.iva_automatico
        return datos

class DetallesBase(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        productos = set()
        suma = Decimal("0")
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            producto = form.cleaned_data.get("producto")
            if producto:
                if producto.pk in productos:
                    raise forms.ValidationError("Cada producto debe aparecer una sola vez. Suma sus cantidades.")
                productos.add(producto.pk)
                with localcontext() as contexto:
                    contexto.prec = 60
                    suma += form.instance.total
        tasa = self.instance.tasa_cambio
        if tasa and tasa > 0:
            with localcontext() as contexto:
                contexto.prec = 60
                en_usd = suma if self.instance.divisa == "USD" else suma / tasa
                en_bs = suma if self.instance.divisa == "BS" else suma * tasa
                if max(suma, en_usd, en_bs) >= Decimal("100000000000000000000"):
                    raise forms.ValidationError("El total convertido excede el límite de 20 dígitos. Revisa precios, cantidades y tasa.")

DetalleFormSet = inlineformset_factory(Compra, DetalleCompra, form=DetalleForm,
    formset=DetallesBase, extra=1, can_delete=True, min_num=1, validate_min=True,
    max_num=100, validate_max=True, absolute_max=100)

class ProveedorConsultaField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre


class FiltroCompras(forms.Form):
    proveedor = ProveedorConsultaField(Proveedor.objects.all(), required=False)
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    factura = forms.CharField(required=False, max_length=60, label="Número de factura")
    producto = forms.CharField(required=False, max_length=50, label="Código de producto")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha desde no puede ser posterior a la fecha hasta.")
        return datos
