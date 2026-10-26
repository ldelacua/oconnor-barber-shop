from decimal import Decimal,InvalidOperation,ROUND_DOWN
from django import forms
from ventas.calculos import dinero

class NumeroDosDecimales(forms.NumberInput):
    def format_value(self,value):
        if value in (None,""):return None
        try:return format(dinero(value),".2f")
        except (InvalidOperation,ValueError,TypeError):return super().format_value(value)

def configurar_decimales(form):
    for campo in form.fields.values():
        if isinstance(campo,forms.DecimalField) and campo.decimal_places==2:
            atributos=dict(campo.widget.attrs)
            atributos["step"]="0.01"
            campo.widget=NumeroDosDecimales(attrs=atributos)

def disponible_visible(valor):
    return Decimal(valor).quantize(Decimal(".01"),rounding=ROUND_DOWN)
