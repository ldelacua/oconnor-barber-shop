import uuid
from decimal import Decimal
from django import forms
from django.forms import formset_factory
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from .models import EntidadConvenio
from citas.buscador_clientes import BuscadorClienteWidget


class VentaForm(forms.Form):
    codigo_regalo = forms.CharField(required=False, max_length=24, label="Código de tarjeta de regalo",
                                  widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "off", "placeholder": "Código completo o últimos 6 caracteres"}))
    fecha = forms.DateField(initial=timezone.localdate, disabled=True, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}))
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.filter(activo=True), widget=BuscadorClienteWidget())
    hora_atencion = forms.TimeField(required=False, label="Hora de atención",
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "form-control"}))
    entidad = forms.ModelChoiceField(queryset=EntidadConvenio.objects.filter(activa=True).order_by("nombre"),
        required=False, label="Convenio", empty_label="Sin convenio", widget=forms.Select(attrs={"class": "form-select"}))
    cita_id = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    aplicar_descuento = forms.BooleanField(required=False, label="Aplicar descuento al cliente", widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    descuento_porcentaje = forms.DecimalField(required=False, initial=Decimal("50.00"), max_digits=5, decimal_places=2,
        min_value=Decimal("0.01"), max_value=Decimal("100.00"), label="Descuento (%)",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "max": "100", "step": "0.01"}))
    clave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


    def clean(self):
        datos = super().clean()
        if datos.get("aplicar_descuento") and datos.get("descuento_porcentaje") is None and "descuento_porcentaje" not in self.errors:
            self.add_error("descuento_porcentaje", "Introduce el porcentaje de descuento.")
        if not datos.get("aplicar_descuento"):
            datos["descuento_porcentaje"] = Decimal("0.00")
        return datos


class PrestadorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, prestador):
        return f"{prestador.nombre} {prestador.apellido}"


class ServicioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, servicio):
        return servicio.nombre


class LineaForm(forms.Form):
    aplicar_promocion = forms.BooleanField(required=False, label="Promoción")
    promocion = forms.ChoiceField(required=False, label="Motivo de promoción", choices=[
        ("", "Selecciona un motivo"), ("FIDELIDAD", "Fidelidad"), ("MARKETING", "Marketing"),
    ], widget=forms.Select(attrs={"class": "form-select promocion-venta"}))

    barbero = PrestadorChoiceField(
        queryset=Barbero.objects.filter(activo=True),
        label="Prestador de servicio",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    servicio = ServicioChoiceField(queryset=Servicio.objects.filter(activo=True), widget=forms.Select(attrs={"class": "form-select servicio-venta"}))
    cantidad_servicio = forms.IntegerField(label="Cantidad", min_value=1, max_value=10000, initial=1, widget=forms.NumberInput(attrs={"class": "form-control cantidad-venta", "min": 1}))

    precio_unitario_usd = forms.DecimalField(required=False, max_digits=18, decimal_places=2, min_value=Decimal("0.00"),
        label="Precio USD", widget=forms.NumberInput(attrs={"class": "form-control precio-manual", "min": "0.01", "step": "0.01"}))

    def clean(self):
        datos = super().clean()
        if datos.get("aplicar_promocion") and not datos.get("promocion") and "promocion" not in self.errors:
            self.add_error("promocion", "Selecciona el motivo de la promoción.")
        if not datos.get("aplicar_promocion"):
            datos["promocion"] = ""
        servicio = datos.get("servicio")
        if servicio and servicio.modo_precio == "manual":
            if datos.get("precio_unitario_usd") is None and "precio_unitario_usd" not in self.errors:
                self.add_error("precio_unitario_usd", "Introduce el precio de este servicio manual.")
            elif datos.get("precio_unitario_usd") is not None and datos["precio_unitario_usd"] <= 0:
                self.add_error("precio_unitario_usd", "El precio manual debe ser mayor que cero.")
        return datos


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

    def __init__(self, *args, catalogo=None, usuario=None, exigir_cuenta=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.exigir_cuenta = exigir_cuenta
        if usuario and usuario.has_perms(('bancos.add_movimientointerno', 'bancos.view_cuentabancaria')):
            from bancos.models import CuentaBancaria
            self.fields['cuenta_bancaria'] = forms.ModelChoiceField(
                queryset=CuentaBancaria.objects.filter(activa=True, banco__activo=True).select_related('banco'),
                required=False, empty_label='Sin banco ni cuenta', label='Banco y cuenta',
                widget=forms.Select(attrs={'class': 'form-select mt-1', 'aria-label': 'Banco y cuenta'}))
        catalogo = catalogo or {}
        self.catalogo_pagos = catalogo
        self.fields['tipo_pago'].widget.attrs['data-tipos-banco'] = ','.join(
            str(codigo) for codigo, tipo in catalogo.items() if tipo.get('afecta_banco', codigo in (1, 2, 3, 4)))
        self.fields["tipo_pago"].choices = [("", "Seleccione")] + [
            (str(codigo), f'{tipo["nombre"]} ({tipo["moneda"]})')
            for codigo, tipo in catalogo.items()
        ]

    def clean(self):
        datos = super().clean()
        codigo = int(datos.get('tipo_pago') or 0)
        tipo = self.catalogo_pagos.get(codigo, {})
        afecta = tipo.get('afecta_banco', codigo in (1, 2, 3, 4))
        cuenta = datos.get('cuenta_bancaria')
        if cuenta and not afecta:
            self.add_error('cuenta_bancaria', 'Esta forma de pago no afecta al banco. Deja la cuenta vacía.')
        elif self.exigir_cuenta and afecta and not cuenta:
            if 'cuenta_bancaria' not in self.fields:
                self.add_error('tipo_pago', 'No tienes permiso para registrar pagos bancarios.')
            elif 'cuenta_bancaria' not in self.errors:
                self.add_error('cuenta_bancaria', 'Selecciona el banco y la cuenta para este pago.')
        elif self.exigir_cuenta and cuenta and cuenta.moneda != tipo.get('moneda'):
            self.add_error('cuenta_bancaria', 'La moneda de la cuenta debe coincidir con la del pago.')
        return datos


PagosFormSet = formset_factory(PagoForm, extra=0, min_num=1, validate_min=True, max_num=20, validate_max=True, absolute_max=25, can_delete=True)
# Solo Ventas admite no recibir pagos cuando el descuento deja el total en cero.
PagosVentaFormSet = formset_factory(PagoForm, extra=1, min_num=0, validate_min=True, max_num=20, validate_max=True, absolute_max=25, can_delete=True)
