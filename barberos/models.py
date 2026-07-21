from django.db import models


class Barbero(models.Model):
    codigo = models.CharField(
        max_length=10,
        unique=True,
        verbose_name="Código"
    )

    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)

    direccion = models.CharField(max_length=250)

    telefono = models.CharField(max_length=20)

    correo = models.EmailField(blank=True)

    fecha_ingreso = models.DateField()

    porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Porcentaje de comisión"
    )

    codigo_silla = models.CharField(
        max_length=10,
        unique=True
    )

    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "apellido"]
        verbose_name = "Barbero"
        verbose_name_plural = "Barberos"

    def __str__(self):
        return f"{self.codigo} - {self.nombre} {self.apellido}"