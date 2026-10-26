from django.core.exceptions import ValidationError
from django.db import models


class Silla(models.Model):
    nombre = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Nombre",
    )

    activa = models.BooleanField(
        default=True,
        verbose_name="Activa",
    )

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Silla"
        verbose_name_plural = "Sillas"

    def __str__(self):
        return self.nombre


class Horario(models.Model):
    DIAS_SEMANA = [
        (1, "Lunes"),
        (2, "Martes"),
        (3, "Miércoles"),
        (4, "Jueves"),
        (5, "Viernes"),
        (6, "Sábado"),
        (7, "Domingo"),
    ]

    barbero = models.ForeignKey(
        "barberos.Barbero",
        on_delete=models.PROTECT,
        related_name="horarios",
        verbose_name="Prestador de Servicio",
    )

    silla = models.ForeignKey(
        Silla,
        on_delete=models.PROTECT,
        related_name="horarios",
        verbose_name="Silla",
    )

    dia_semana = models.PositiveSmallIntegerField(
        choices=DIAS_SEMANA,
        verbose_name="Día de la semana",
    )

    hora_inicio = models.TimeField(
        verbose_name="Hora de inicio",
    )

    hora_fin = models.TimeField(
        verbose_name="Hora de finalización",
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )

    observaciones = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Observaciones",
    )

    class Meta:
        ordering = [
            "dia_semana",
            "hora_inicio",
            "silla",
        ]
        verbose_name = "Horario"
        verbose_name_plural = "Horarios"

    def __str__(self):
        return (
            f"{self.get_dia_semana_display()} - "
            f"{self.barbero} - "
            f"{self.silla} - "
            f"{self.hora_inicio:%H:%M} a {self.hora_fin:%H:%M}"
        )

    def clean(self):
        super().clean()

        errores = {}

        if (
            self.hora_inicio
            and self.hora_fin
            and self.hora_inicio >= self.hora_fin
        ):
            errores["hora_fin"] = (
                "La hora final debe ser posterior a la hora inicial."
            )

        datos_completos = (
            self.dia_semana
            and self.hora_inicio
            and self.hora_fin
        )

        if datos_completos and self.silla_id:
            conflicto_silla = Horario.objects.filter(
                silla_id=self.silla_id,
                dia_semana=self.dia_semana,
                activo=True,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio,
            ).exclude(pk=self.pk)

            if conflicto_silla.exists():
                errores["silla"] = (
                    "La silla ya está ocupada durante ese bloque de horas."
                )

        if datos_completos and self.barbero_id:
            conflicto_barbero = Horario.objects.filter(
                barbero_id=self.barbero_id,
                dia_semana=self.dia_semana,
                activo=True,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio,
            ).exclude(pk=self.pk)

            if conflicto_barbero.exists():
                errores["barbero"] = (
                    "El prestador de servicio ya está asignado a otra silla "
                    "durante ese bloque de horas."
                )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)