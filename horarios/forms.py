import json
from datetime import time

from django import forms

from barberos.models import Barbero

from .models import Horario, Silla


def generar_horas(hora_inicial, minuto_inicial, hora_final, minuto_final):
    """
    Genera valores de hora en intervalos de 30 minutos.

    Ejemplo:
    08:00, 08:30, 09:00...
    """
    opciones = []

    hora = hora_inicial
    minuto = minuto_inicial

    while (hora, minuto) <= (hora_final, minuto_final):
        valor = f"{hora:02d}:{minuto:02d}"

        opciones.append(
            (
                valor,
                valor,
            )
        )

        minuto += 30

        if minuto >= 60:
            minuto = 0
            hora += 1

    return opciones


def convertir_hora(valor):
    """
    Convierte el valor seleccionado, por ejemplo '08:30',
    en un objeto datetime.time.
    """
    if isinstance(valor, time):
        return valor

    if not valor:
        return None

    hora, minuto = map(int, valor.split(":"))

    return time(
        hour=hora,
        minute=minuto,
    )


HORAS_INICIO = generar_horas(
    8,
    0,
    22,
    30,
)

HORAS_FIN = generar_horas(
    8,
    30,
    23,
    0,
)


class SillaForm(forms.ModelForm):
    class Meta:
        model = Silla

        fields = [
            "nombre",
            "activa",
        ]

        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: Silla 1",
                    "autofocus": True,
                }
            ),
            "activa": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }


class MatrizHorarioForm(forms.Form):
    """
    Formulario utilizado para crear horarios mediante
    la matriz semanal interactiva.
    """

    barbero = forms.ModelChoiceField(
        queryset=Barbero.objects.none(),
        label="Barbero",
        empty_label="Seleccione un barbero",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    silla = forms.ModelChoiceField(
        queryset=Silla.objects.none(),
        label="Silla",
        empty_label="Seleccione una silla",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    bloques = forms.CharField(
        widget=forms.HiddenInput(
            attrs={
                "id": "id_bloques",
            }
        ),
    )

    activo = forms.BooleanField(
        required=False,
        initial=True,
        label="Activo",
        widget=forms.CheckboxInput(
            attrs={
                "class": "form-check-input",
            }
        ),
    )

    observaciones = forms.CharField(
        required=False,
        max_length=150,
        label="Observaciones",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "Ejemplo: Suplencia temporal o bloque especial."
                ),
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["barbero"].queryset = (
            Barbero.objects.all().order_by("nombre", "apellido")
        )

        self.fields["silla"].queryset = (
            Silla.objects.filter(activa=True).order_by("nombre")
        )

    def clean_bloques(self):
        valor = self.cleaned_data.get("bloques")

        try:
            bloques = json.loads(valor)
        except (TypeError, json.JSONDecodeError):
            raise forms.ValidationError(
                "La selección de horarios no es válida."
            )

        if not isinstance(bloques, dict):
            raise forms.ValidationError(
                "La selección de horarios no tiene el formato esperado."
            )

        if not any(bloques.values()):
            raise forms.ValidationError(
                "Debe seleccionar al menos un bloque en la matriz."
            )

        return bloques


class HorarioForm(forms.ModelForm):
    """
    Formulario para editar un solo horario y un solo día.
    """

    hora_inicio = forms.TypedChoiceField(
        choices=HORAS_INICIO,
        coerce=convertir_hora,
        empty_value=None,
        label="Hora de inicio",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "id": "id_hora_inicio",
            }
        ),
    )

    hora_fin = forms.TypedChoiceField(
        choices=HORAS_FIN,
        coerce=convertir_hora,
        empty_value=None,
        label="Hora de finalización",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "id": "id_hora_fin",
            }
        ),
    )

    class Meta:
        model = Horario

        fields = [
            "barbero",
            "silla",
            "dia_semana",
            "hora_inicio",
            "hora_fin",
            "activo",
            "observaciones",
        ]

        widgets = {
            "barbero": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "silla": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "dia_semana": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "activo": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
            "observaciones": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["silla"].queryset = (
            Silla.objects.filter(activa=True).order_by("nombre")
        )

    def clean(self):
        cleaned_data = super().clean()

        hora_inicio = cleaned_data.get("hora_inicio")
        hora_fin = cleaned_data.get("hora_fin")

        if (
            hora_inicio
            and hora_fin
            and hora_fin <= hora_inicio
        ):
            self.add_error(
                "hora_fin",
                "La hora final debe ser posterior a la hora inicial.",
            )

        return cleaned_data