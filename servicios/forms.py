from django import forms

from .models import Servicio


class ServicioForm(forms.ModelForm):
    class Meta:
        model = Servicio

        fields = [
            "codigo",
            "nombre",
            "descripcion",
            "modo_precio",
            "precio",
            "duracion",
            "retencion_impuesto",
            "activo",
        ]

        widgets = {
            "modo_precio": forms.Select(attrs={"class": "form-select"}),
            "codigo": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: SER001",
                }
            ),
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre del servicio",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descripción del servicio",
                }
            ),
            "precio": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "duracion": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "retencion_impuesto": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "activo": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["precio"].required = False
        self.fields["precio"].help_text = "Automático: precio de venta. Manual: el precio se introduce al facturar; puedes dejar este valor en cero."

    def clean(self):
        datos = super().clean()
        if "precio" not in self.errors:
            precio = datos.get("precio")
            if precio is None:
                if datos.get("modo_precio") == "manual":
                    datos["precio"] = 0
                else:
                    self.add_error("precio", "Introduce el precio del servicio automático.")
            elif precio < 0:
                self.add_error("precio", "El precio no puede ser negativo.")
        return datos
