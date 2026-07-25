from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio


class Cita(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        CONFIRMADA = "confirmada", "Confirmada"
        CANCELADA = "cancelada", "Cancelada"
        FINALIZADA = "finalizada", "Finalizada"

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="citas",
    )

    barbero = models.ForeignKey(
        Barbero,
        on_delete=models.PROTECT,
        related_name="citas",
    )

    # Campo antiguo. Se mantiene temporalmente para conservar las citas existentes.
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.PROTECT,
        related_name="citas",
    )

    # Nuevo campo para permitir varios servicios por cita.
    servicios = models.ManyToManyField(
        Servicio,
        related_name="citas_multiples",
        verbose_name="Servicios",
        blank=True,
    )

    fecha = models.DateField()
    hora = models.TimeField()

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    observaciones = models.TextField(
        blank=True,
    )

    creado_en = models.DateTimeField(
        auto_now_add=True,
    )

    actualizado_en = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["fecha", "hora"]
        verbose_name = "Cita"
        verbose_name_plural = "Citas"

        constraints = [
            models.UniqueConstraint(
                fields=["barbero", "fecha", "hora"],
                condition=~models.Q(estado="cancelada"),
                name="cita_barbero_fecha_hora_unica",
            )
        ]

    def __str__(self):
        return (
            f"{self.cliente} - {self.barbero} - "
            f"{self.fecha} {self.hora}"
        )

    @property
    def duracion_total(self):
        if self.pk and self.servicios.exists():
            return sum(
                servicio.duracion
                for servicio in self.servicios.all()
            )

        if self.servicio_id:
            return self.servicio.duracion

        return 0

    @property
    def precio_total(self):
        if self.pk and self.servicios.exists():
            return sum(
                servicio.precio
                for servicio in self.servicios.all()
            )

        if self.servicio_id:
            return self.servicio.precio

        return 0

    def clean(self):
        errores = {}

        if self.fecha and self.fecha < timezone.localdate():
            errores["fecha"] = (
                "No puedes crear una cita en una fecha pasada."
            )

        if self.barbero_id and self.fecha and self.hora:
            citas_existentes = Cita.objects.filter(
                barbero_id=self.barbero_id,
                fecha=self.fecha,
                hora=self.hora,
            ).exclude(
                estado=self.Estado.CANCELADA,
            )

            if self.pk:
                citas_existentes = citas_existentes.exclude(pk=self.pk)

            if citas_existentes.exists():
                errores["hora"] = (
                    "El barbero ya tiene una cita programada "
                    "en esa fecha y hora."
                )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)