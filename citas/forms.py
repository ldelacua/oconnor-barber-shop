from datetime import date, datetime
from .buscador_clientes import BuscadorClienteWidget
from django import forms

from servicios.models import Servicio

from .disponibilidad import obtener_horas_disponibles
from .models import Cita


class ServiciosMultipleChoiceField(
    forms.ModelMultipleChoiceField
):
    def label_from_instance(self, servicio):
        return (
            f"{servicio.nombre} · "
            f"{servicio.duracion} min · "
            f"${servicio.precio}"
        )


class CitaForm(forms.ModelForm):
    servicios = ServiciosMultipleChoiceField(
        queryset=Servicio.objects.none(),
        label="Servicios",
        required=True,
        widget=forms.CheckboxSelectMultiple(),
        help_text=(
            "Selecciona uno o varios servicios para esta cita."
        ),
    )

    hora = forms.ChoiceField(
        choices=[],
        label="Hora disponible",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    class Meta:
        model = Cita

        fields = [
            "cliente",
            "barbero",
            "servicios",
            "fecha",
            "hora",
            "estado",
            "observaciones",
        ]

        widgets = {
            "cliente": BuscadorClienteWidget()
            ,            
            "Prestador de Servicio": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "fecha": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                },
                format="%Y-%m-%d",
            ),
            "estado": forms.Select(
                attrs={
                    "class": "form-select",
                }
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

        servicios_queryset = Servicio.objects.filter(
            activo=True
        ).order_by("nombre")

        self.fields["servicios"].queryset = (
            servicios_queryset
        )

        opciones_hora = [
            ("", "Seleccione una hora"),
        ]

        barbero_id = None
        servicios_ids = []
        fecha = None
        hora_inicial = None

        # Formulario enviado mediante POST.
        if self.is_bound:
            barbero_id = self.data.get("barbero")

            servicios_ids = self.data.getlist(
                "servicios"
            )

            fecha = self._convertir_fecha(
                self.data.get("fecha")
            )

            hora_inicial = self.data.get("hora")

        # Edición de una cita existente.
        elif self.instance and self.instance.pk:
            barbero_id = self.instance.barbero_id
            fecha = self.instance.fecha

            hora_inicial = (
                self.instance.hora.strftime("%H:%M")
                if self.instance.hora
                else None
            )

            servicios_ids = list(
                self.instance.servicios.values_list(
                    "pk",
                    flat=True,
                )
            )

            # Compatibilidad con citas antiguas que todavía
            # solo tienen el campo servicio.
            if (
                not servicios_ids
                and self.instance.servicio_id
            ):
                servicios_ids = [
                    self.instance.servicio_id
                ]

            self.initial["servicios"] = servicios_ids

        # Nueva cita abierta desde la agenda.
        else:
            barbero_id = self.initial.get("barbero")

            servicios_iniciales = self.initial.get(
                "servicios",
                [],
            )

            if servicios_iniciales:
                if isinstance(
                    servicios_iniciales,
                    (list, tuple),
                ):
                    servicios_ids = list(
                        servicios_iniciales
                    )
                else:
                    servicios_ids = [
                        servicios_iniciales
                    ]

            fecha = self._convertir_fecha(
                self.initial.get("fecha")
            )

            hora_inicial = self.initial.get("hora")

        servicios_seleccionados = list(
            Servicio.objects.filter(
                pk__in=servicios_ids,
                activo=True,
            )
        )

        if (
            barbero_id
            and servicios_seleccionados
            and fecha
        ):
            try:
                horas = obtener_horas_disponibles(
                    barbero_id=barbero_id,
                    servicios=servicios_seleccionados,
                    fecha=fecha,
                    cita_id=(
                        self.instance.pk
                        if self.instance
                        and self.instance.pk
                        else None
                    ),
                )

                # Al editar se conserva la hora actual.
                if (
                    hora_inicial
                    and hora_inicial not in horas
                    and self.instance
                    and self.instance.pk
                ):
                    horas.append(hora_inicial)

                horas.sort()

                opciones_hora.extend(
                    (hora, hora)
                    for hora in horas
                )

            except (TypeError, ValueError) as error:
               self.add_error(
               None,
              f"No fue posible calcular las horas: {error}",
                )

        # Cuando se abre desde la agenda todavía no hay
        # servicios seleccionados. Conservamos la hora para
        # que JavaScript pueda seleccionarla después.
        elif hora_inicial:
            opciones_hora.append(
                (hora_inicial, hora_inicial)
            )

        self.fields["hora"].choices = opciones_hora

        if hora_inicial:
            self.initial["hora"] = hora_inicial

    @staticmethod
    def _convertir_fecha(valor):
        if not valor:
            return None

        if isinstance(valor, datetime):
            return valor.date()

        if isinstance(valor, date):
            return valor

        try:
            return datetime.strptime(
                str(valor),
                "%Y-%m-%d",
            ).date()
        except (TypeError, ValueError):
            return None

    def clean_servicios(self):
        servicios = self.cleaned_data.get(
            "servicios"
        )

        if not servicios:
            raise forms.ValidationError(
                "Debes seleccionar al menos un servicio."
            )

        return servicios

    def clean_hora(self):
        hora_texto = self.cleaned_data.get("hora")

        if not hora_texto:
            raise forms.ValidationError(
                "Debes seleccionar una hora."
            )

        try:
            return datetime.strptime(
                hora_texto,
                "%H:%M",
            ).time()
        except (TypeError, ValueError):
            raise forms.ValidationError(
                "La hora seleccionada no es válida."
            )

    def save(self, commit=True):
        """
        Guarda los servicios múltiples y mantiene temporalmente
        sincronizado el campo antiguo servicio.
        """

        cita = super().save(commit=False)

        servicios = list(
            self.cleaned_data.get("servicios", [])
        )

        if servicios:
            # Mantener el primer servicio en el campo antiguo
            # hasta completar toda la migración.
            cita.servicio = servicios[0]

        if commit:
            cita.save()

            # Guarda el campo ManyToMany.
            self.save_m2m()

        return cita