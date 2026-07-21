from django import forms

from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente

        fields = [
            "nombre",
            "apellido",
            "telefono",
            "email",
            "direccion",
            "fecha_nacimiento",
            "observaciones",
            "activo",
        ]

        widgets = {
            "nombre": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "apellido": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "telefono": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control"}
            ),
            "direccion": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "fecha_nacimiento": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "observaciones": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                }
            ),
            "activo": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }