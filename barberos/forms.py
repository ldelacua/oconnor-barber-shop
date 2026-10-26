from django import forms
from django.db.models import Q
from horarios.models import Silla
from .models import Barbero


class BarberoForm(forms.ModelForm):
    class Meta:
        model = Barbero
        fields = ["codigo", "nombre", "apellido", "direccion", "telefono", "correo",
                  "fecha_ingreso", "porcentaje", "silla", "activo"]
        labels = {
            "codigo": "Código", "direccion": "Dirección", "telefono": "Teléfono",
            "correo": "Correo electrónico", "fecha_ingreso": "Fecha de ingreso",
            "porcentaje": "Porcentaje de comisión", "silla": "Silla",
            "activo": "Prestador de Servicio activo",
        }
        widgets = {
            "fecha_ingreso": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "porcentaje": forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01"}),
        }
        help_texts = {"porcentaje": "Introduce un porcentaje entre 0 y 100."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["class"] = (
                "form-check-input" if isinstance(campo.widget, forms.CheckboxInput)
                else "form-select" if isinstance(campo.widget, forms.Select)
                else "form-control"
            )
        self.fields["silla"].required = True
        self.fields["silla"].empty_label = "Selecciona una silla"
        self.fields["silla"].queryset = Silla.objects.filter(
            Q(activa=True) | Q(pk=self.instance.silla_id)
        ).order_by("nombre")
        self.fields["silla"].help_text = "Si no aparece la silla, regístrala desde Administrar sillas."

    def clean_silla(self):
        silla = self.cleaned_data["silla"]
        if not silla.activa and silla.pk != self.instance.silla_id:
            raise forms.ValidationError("Selecciona una silla activa.")
        return silla

    def clean_porcentaje(self):
        valor = self.cleaned_data["porcentaje"]
        if not 0 <= valor <= 100:
            raise forms.ValidationError("La comisión debe estar entre 0 y 100.")
        return valor

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()

    def clean_nombre(self):
        return self.cleaned_data["nombre"].strip().title()

    def clean_apellido(self):
        return self.cleaned_data["apellido"].strip().title()
