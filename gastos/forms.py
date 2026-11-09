from decimal import Decimal
from django import forms
from django.forms.models import BaseInlineFormSet
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
            if isinstance(campo, forms.CharField):
                campo.widget.attrs["data-mayusculas-gastos"] = "1"
            if isinstance(campo,forms.DecimalField):
                campo.widget.attrs.update({"step":"0.01","min":"0"})
    def clean(self):
        datos = super().clean()
        for nombre, campo in self.fields.items():
            if isinstance(campo, forms.CharField) and isinstance(datos.get(nombre), str):
                datos[nombre] = datos[nombre].strip().upper()
        return datos


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
    tipo_pago = forms.TypedChoiceField(coerce=int, empty_value=None, label='Forma de pago', required=False)

    class Meta:
        model=RegistroGasto
        fields=["fecha_gasto","gasto","proveedor","numero_factura","numero_control","moneda","monto_gasto","monto_impuesto","porcentaje_impuesto","tipo_pago","referencia_pago"]
        widgets={"fecha_gasto":forms.DateInput(format="%Y-%m-%d",attrs={"type":"date"})}

    def __init__(self,*args,usuario=None,registro_detallado=False,**kwargs):
        super().__init__(*args,**kwargs)
        if registro_detallado:
            for nombre in ("monto_gasto", "monto_impuesto", "porcentaje_impuesto", "moneda"):
                self.fields[nombre].widget = forms.HiddenInput()
            self.fields["monto_pago"] = forms.DecimalField(
                label="Monto pagado", max_digits=19, decimal_places=2, min_value=Decimal("0.01"),
                required=not self.instance.pk or bool(self.instance.tipo_pago),
                initial=self.instance.total if self.instance.pk else None,
                widget=forms.NumberInput(attrs={"class": "form-control text-end", "step": "0.01", "min": "0.01", "readonly": True}))
        from ventas.pagos_calculos import leer_tipos_pago
        self.catalogo_pagos = leer_tipos_pago()
        self.fields['tipo_pago'].widget.attrs['data-tipos-banco'] = ','.join(
            str(codigo) for codigo, tipo in self.catalogo_pagos.items() if tipo.get('afecta_banco'))
        if usuario and usuario.has_perms(('bancos.view_cuentabancaria', 'bancos.add_movimientointerno')):
            from bancos.models import CuentaBancaria
            self.fields['cuenta_bancaria'] = forms.ModelChoiceField(
                queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True).select_related('banco'),
                required=False, label='Banco y cuenta', widget=forms.Select(attrs={'class':'form-select'}))

        if self.instance.tipo_pago and self.instance.tipo_pago not in self.catalogo_pagos:
            self.catalogo_pagos[self.instance.tipo_pago] = {
                'nombre': self.instance.nombre_tipo_pago, 'moneda': self.instance.moneda}
        if registro_detallado and self.is_bound:
            try:
                codigo = int(self.data.get(self.add_prefix("tipo_pago")) or 0)
            except ValueError:
                codigo = 0
            tipo = self.catalogo_pagos.get(codigo)
            self.data = self.data.copy()
            self.data[self.add_prefix("moneda")] = tipo["moneda"] if tipo else (self.instance.moneda or "BS")
        self.fields['tipo_pago'].choices = [('', 'Selecciona cómo se pagó')] + [
            (codigo, f"{tipo['nombre']} ({tipo['moneda']})") for codigo, tipo in self.catalogo_pagos.items()]
        self.fields['tipo_pago'].required = not self.instance.pk or bool(self.instance.tipo_pago)
        self.fields["gasto"].queryset=TipoGasto.objects.filter(Q(activo=True,grupo__activo=True)|Q(pk=self.instance.gasto_id)).select_related("grupo")
        self.fields["proveedor"].queryset=Proveedor.objects.filter(Q(activo=True)|Q(pk=self.instance.proveedor_id))
        self.fields["monto_gasto"].widget.attrs["min"]="0.01"
        self.fields['numero_factura'].required = False
        for nombre in ('numero_factura', 'numero_control'):
            self.fields[nombre].help_text = 'Si se deja vacío, se asigna el ID interno del documento al guardar.'


    def clean(self):
        datos=super().clean()
        if "monto_pago" in self.fields and datos.get("fecha_gasto"):
            fecha = datos["fecha_gasto"]
            if self.instance.pk and self.instance.fecha_gasto == fecha and self.instance.tasa_bcv is not None:
                datos["tasa_bcv"] = self.instance.tasa_bcv
            else:
                from tasas_bcv.models import TasaBCV
                tasa = TasaBCV.objects.filter(fecha=fecha).values_list("tasa_bcv", flat=True).first()
                if tasa is None or tasa <= 0:
                    self.add_error("fecha_gasto", "No hay una tasa BCV válida para esta fecha. Regístrala en Tasas Bs.")
                else:
                    datos["tasa_bcv"] = tasa
        if "monto_pago" in self.fields and datos.get("monto_pago") is not None:
            base, impuesto = datos.get("monto_gasto"), datos.get("monto_impuesto")
            if base is not None and impuesto is not None and datos["monto_pago"] != base + impuesto:
                self.add_error("monto_pago", f"El monto pagado debe ser igual al total del gasto: {base + impuesto:,.2f}.")
        codigo = datos.get('tipo_pago')
        tipo = self.catalogo_pagos.get(codigo)
        if tipo and datos.get('moneda') and tipo['moneda'] != datos['moneda']:
            self.add_error('tipo_pago', 'La forma de pago debe tener la misma moneda que el gasto.')
        elif tipo and codigo != self.instance.tipo_pago:
            self.instance.nombre_tipo_pago = tipo['nombre'].upper()
        cuenta = datos.get('cuenta_bancaria')
        if tipo and tipo.get('afecta_banco') and not cuenta and 'cuenta_bancaria' not in self.errors:
            self.add_error('cuenta_bancaria' if 'cuenta_bancaria' in self.fields else None,
                           'Selecciona una cuenta bancaria. Si no tienes acceso, consulta al administrador.')
        elif cuenta and (not tipo or not tipo.get('afecta_banco') or cuenta.moneda != datos.get('moneda')):
            self.add_error('cuenta_bancaria', 'La forma de pago debe afectar al banco y la cuenta debe tener la misma moneda.')
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
            "facturable",
            "activo",
        ]


class DetalleGastoForm(EstiloForm):
    class Meta:
        model = DetalleRegistroGasto
        fields = ["producto", "cantidad", "precio_unitario", "impuesto_linea"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto"].queryset = Producto.objects.filter(
            Q(activo=True) | Q(pk=self.instance.producto_id))
        self.fields["impuesto_linea"].required = False
        self.fields["impuesto_linea"].initial = None
        for campo in ("precio_unitario", "impuesto_linea"):
            self.fields[campo].widget.attrs.update({"min": "0", "step": "0.01", "class": "form-control text-end"})
        self.fields["cantidad"].widget.attrs.update({"step": "0.001", "min": "0.001"})

    def clean(self):
        datos = super().clean()
        datos["impuesto_linea"] = datos.get("impuesto_linea") or Decimal("0")
        if datos.get("precio_unitario") is None and (
            not self.instance.pk or self.instance.precio_unitario is not None or datos["impuesto_linea"]
        ) and "precio_unitario" not in self.errors:
            self.add_error("precio_unitario", "Indica el precio unitario antes de impuesto.")
        return datos

    def clean_producto(self):
        producto = self.cleaned_data["producto"]
        if not producto.activo and producto.pk != self.instance.producto_id:
            raise forms.ValidationError("Selecciona un producto activo.")
        return producto


class BaseDetalleGastoFormSet(BaseInlineFormSet):
    totales = None

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        lineas = [f.instance for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        valorizadas = [l for l in lineas if l.precio_unitario is not None]
        if valorizadas and len(valorizadas) != len(lineas):
            raise forms.ValidationError("Completa el precio de todos los productos para calcular el total del gasto.")
        if valorizadas:
            self.totales = (sum(l.subtotal for l in valorizadas), sum(l.impuesto_linea for l in valorizadas))


DetalleGastoFormSet = inlineformset_factory(
    RegistroGasto, DetalleRegistroGasto, form=DetalleGastoForm, formset=BaseDetalleGastoFormSet,
    extra=1, can_delete=True, max_num=100, validate_max=True, absolute_max=200,
)
