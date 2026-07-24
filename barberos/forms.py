from django import forms

from .models import Barbero


class BarberoForm(forms.ModelForm):
    class Meta:
        model = Barbero

        fields = [
            "codigo",
            "nombre",
            "apellido",
            "direccion",
            "telefono",
            "correo",
            "fecha_ingreso",
            "porcentaje",
            "codigo_silla",
            "activo",
        ]

        widgets = {
            "codigo": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: BAR001",
                }
            ),
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre del barbero",
                }
            ),
            "apellido": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Apellido del barbero",
                }
            ),
            "direccion": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Dirección",
                }
            ),
            "telefono": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Número de teléfono",
                }
            ),
            "correo": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "correo@ejemplo.com",
                }
            ),
            "fecha_ingreso": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "porcentaje": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: 50.00",
                    "min": "0",
                    "max": "100",
                    "step": "0.01",
                }
            ),
            "codigo_silla": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: S01",
                }
            ),
            "activo": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        labels = {
            "codigo": "Código",
            "nombre": "Nombre",
            "apellido": "Apellido",
            "direccion": "Dirección",
            "telefono": "Teléfono",
            "correo": "Correo electrónico",
            "fecha_ingreso": "Fecha de ingreso",
            "porcentaje": "Porcentaje de comisión",
            "codigo_silla": "Código de silla",
            "activo": "Barbero activo",
        }

        help_texts = {
            "porcentaje": "Introduce un porcentaje entre 0 y 100.",
        }

    def clean_codigo(self):
        codigo = self.cleaned_data["codigo"].strip().upper()
        return codigo

    def clean_codigo_silla(self):
        codigo_silla = self.cleaned_data["codigo_silla"].strip().upper()
        return codigo_silla

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        return nombre.title()

    def clean_apellido(self):
        apellido = self.cleaned_data["apellido"].strip()
        return apellido.title()