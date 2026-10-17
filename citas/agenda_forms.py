from django import forms
from django.utils import timezone
from .forms import CitaForm
from .disponibilidad import obtener_horas_disponibles


class CitaAgendaForm(CitaForm):
    """Nueva cita con el hueco de Agenda fijado por la vista."""

    def __init__(self, *args, seleccion, **kwargs):
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.update(seleccion)
        kwargs["initial"] = initial

        # El formulario base calcula las opciones desde data al recibir POST.
        # Usamos los valores verificados, nunca los campos enviados por el navegador.
        args = list(args)
        if args and args[0] is not None:
            data = args[0].copy()
            data.update(seleccion)
            args[0] = data
        elif kwargs.get("data") is not None:
            data = kwargs["data"].copy()
            data.update(seleccion)
            kwargs["data"] = data

        super().__init__(*args, **kwargs)
        self.fields["hora"].choices = [(seleccion["hora"], seleccion["hora"])]
        for nombre in ("barbero", "fecha", "hora"):
            self.fields[nombre].disabled = True

    def clean(self):
        datos = super().clean()
        barbero = datos.get("barbero")
        fecha = datos.get("fecha")
        hora = datos.get("hora")
        ahora = timezone.localtime()

        if (
            fecha
            and hora
            and (
                fecha < ahora.date()
                or (
                    fecha == ahora.date()
                    and hora < ahora.time()
                )
            )
        ):
            self.add_error(
                "hora",
                "Este horario ya pasó. Vuelve a Agenda "
                "y selecciona una hora futura.",
            )
            return datos
        servicios = datos.get("servicios")
        if barbero and fecha and hora and servicios:
            horas = obtener_horas_disponibles(
                barbero_id=barbero.pk,
                servicios=list(servicios),
                fecha=fecha,
                cita_id=None,
            )
            if hora.strftime("%H:%M") not in horas:
                self.add_error("servicios", forms.ValidationError(
                    "Los servicios no caben en el horario elegido o el hueco "
                    "ya no está disponible. Cambia los servicios o vuelve a "
                    "Agenda para elegir otro hueco."
                ))
        return datos
