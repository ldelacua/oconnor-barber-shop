from django.db import models


class Servicio(models.Model):
    codigo = models.CharField(
        max_length=10,
        unique=True,
        verbose_name="Código"
    )

    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre del servicio"
    )

    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )

    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    duracion = models.PositiveIntegerField(
        verbose_name="Duración (minutos)"
    )

    modo_precio = models.CharField(
        max_length=10,
        choices=[("automatico", "Automático"), ("manual", "Manual")],
        default="automatico", verbose_name="Tipo de precio",
    )

    retencion_impuesto = models.BooleanField(default=False, verbose_name="Retención de impuesto")

    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Servicio"
        verbose_name_plural = "Servicios"

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"
