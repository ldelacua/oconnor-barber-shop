from django.db import models


class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)

    telefono = models.CharField(max_length=20)

    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Correo electrónico"
    )

    direccion = models.CharField(
        max_length=250,
        blank=True
    )

    fecha_nacimiento = models.DateField(
        blank=True,
        null=True
    )

    fecha_registro = models.DateTimeField(
        auto_now_add=True
    )

    observaciones = models.TextField(
        blank=True
    )

    activo = models.BooleanField(
        default=True
    )

    class Meta:
        ordering = ["nombre", "apellido"]
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"