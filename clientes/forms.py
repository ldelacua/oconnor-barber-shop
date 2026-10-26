from django import forms
from .models import Cliente, CAMPOS_MAYUSCULAS

MESES = [(1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
         (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
         (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre")]


class ClienteForm(forms.ModelForm):
    dia_nacimiento = forms.TypedChoiceField(
        label="Día de nacimiento", required=False, coerce=int, empty_value=None,
        choices=[("", "Día")] + [(n, n) for n in range(1, 32)])
    mes_nacimiento = forms.TypedChoiceField(
        label="Mes de nacimiento", required=False, coerce=int, empty_value=None,
        choices=[("", "Mes")] + MESES)

    class Meta:
        model = Cliente
        fields = ["nombre", "apellido", "telefono", "email", "direccion",
                  "dia_nacimiento", "mes_nacimiento", "observaciones", "activo"]
        widgets = {
            "telefono": forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]{11}",
                                               "minlength": "11", "maxlength": "11",
                                               "title": "Exactamente 11 dígitos (0-9)"}),
            "observaciones": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, campo in self.fields.items():
            campo.widget.attrs["class"] = "form-check-input" if nombre == "activo" else (
                "form-select" if isinstance(campo.widget, forms.Select) else "form-control")
            if nombre in CAMPOS_MAYUSCULAS:
                campo.widget.attrs["style"] = "text-transform: uppercase;"
                campo.widget.attrs["data-mayusculas"] = "true"

    def clean(self):
        datos = super().clean()
        for campo in CAMPOS_MAYUSCULAS:
            if datos.get(campo) is not None:
                datos[campo] = datos[campo].upper()
        return datos
