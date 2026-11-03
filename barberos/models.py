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
        unique=True,
        null=True,
        blank=True,
        verbose_name="Código de silla anterior"
    )

    silla = models.ForeignKey(
        "horarios.Silla", on_delete=models.PROTECT,
        null=True, blank=True, related_name="prestadores", verbose_name="Silla"
    )

    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "apellido"]
        verbose_name = "Prestador de Servicio"
        verbose_name_plural = "Prestadores de Servicio"

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        if self.pk and not self._state.adding:
            anterior = type(self).objects.get(pk=self.pk)
            if anterior.silla_id != self.silla_id and self.horarios.exists():
                raise ValidationError('No puedes cambiar la silla porque este prestador tiene horarios registrados.')
        for campo in ('codigo', 'nombre', 'apellido', 'direccion', 'correo'):
            valor = getattr(self, campo)
            if valor is not None:
                setattr(self, campo, valor.strip().upper())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.nombre} {self.apellido}"
