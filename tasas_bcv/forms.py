from django import forms

from .models import TasaBCV


class TasaBCVForm(forms.ModelForm):
    class Meta:
        model = TasaBCV
        fields = ["fecha", "tasa_bcv"]
        widgets = {
            "fecha": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"},
            ),
            "tasa_bcv": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.000001",
                "min": "0.000001",
            }),
        }
        error_messages = {
            "fecha": {"unique": "Ya existe una tasa para esta fecha. Edita el registro existente."},
        }
