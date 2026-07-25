from datetime import datetime

from django import forms

from servicios.models import Servicio

from .disponibilidad import obtener_horas_disponibles
from .models import Cita


class CitaForm(forms.ModelForm):
    hora = forms.ChoiceField(
        choices=[],
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
        label="Hora disponible",
    )

    class Meta:
        model = Cita
        fields = [
            "cliente",
            "barbero",
            "servicio",
            "fecha",
            "hora",
            "estado",
            "observaciones",
        ]

        widgets = {
            "cliente": forms.Select(
                attrs={"class": "form-select"}
            ),
            "barbero": forms.Select(
                attrs={"class": "form-select"}
            ),
            "servicio": forms.Select(
                attrs={"class": "form-select"}
            ),
            "fecha": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "estado": forms.Select(
                attrs={"class": "form-select"}
            ),
            "observaciones": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Observaciones de la cita",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["servicio"].queryset = (
            Servicio.objects.filter(activo=True)
        )

        opciones = [
            ("", "Seleccione una hora")
        ]

        barbero_id = None
        servicio_id = None
        fecha = None

        if self.is_bound:
            barbero_id = self.data.get("barbero")
            servicio_id = self.data.get("servicio")
            fecha_texto = self.data.get("fecha")

            if fecha_texto:
                try:
                    fecha = datetime.strptime(
                        fecha_texto,
                        "%Y-%m-%d",
                    ).date()
                except ValueError:
                    fecha = None

        elif self.instance and self.instance.pk:
            barbero_id = self.instance.barbero_id
            servicio_id = self.instance.servicio_id
            fecha = self.instance.fecha

        if barbero_id and servicio_id and fecha:
            try:
                servicio = Servicio.objects.get(
                    pk=servicio_id,
                    activo=True,
                )

                horas = obtener_horas_disponibles(
                    barbero_id=barbero_id,
                    servicio=servicio,
                    fecha=fecha,
                    cita_id=(
                        self.instance.pk
                        if self.instance
                        else None
                    ),
                )

                hora_actual = None

                if self.instance and self.instance.pk:
                    hora_actual = (
                        self.instance.hora.strftime("%H:%M")
                    )

                    if hora_actual not in horas:
                        horas.append(hora_actual)

                horas.sort()

                opciones.extend(
                    (hora, hora)
                    for hora in horas
                )

            except Servicio.DoesNotExist:
                pass

        self.fields["hora"].choices = opciones

        if self.instance and self.instance.pk:
            self.initial["hora"] = (
                self.instance.hora.strftime("%H:%M")
            )

    def clean_hora(self):
        hora_texto = self.cleaned_data["hora"]

        try:
            return datetime.strptime(
                hora_texto,
                "%H:%M",
            ).time()
        except ValueError:
            raise forms.ValidationError(
                "La hora seleccionada no es válida."
            )