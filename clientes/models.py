from datetime import date
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

CAMPOS_MAYUSCULAS = ("nombre", "apellido", "direccion", "email", "observaciones")
validar_telefono = RegexValidator(r"\A[0-9]{11}\Z", "El teléfono debe contener exactamente 10 dígitos (0-9).")


class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)

    telefono = models.CharField(max_length=20, validators=[validar_telefono])

    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Correo electrónico"
    )

    direccion = models.CharField(
        max_length=250,
        blank=True
    )

    # Campo histórico: se conserva por compatibilidad; no se utiliza en el formulario.
    fecha_nacimiento = models.DateField(
        editable=False,
        blank=True,
        null=True
    )

    dia_nacimiento = models.PositiveSmallIntegerField(blank=True, null=True)
    mes_nacimiento = models.PositiveSmallIntegerField(blank=True, null=True)

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

    def normalizar_mayusculas(self):
        for campo in CAMPOS_MAYUSCULAS:
            valor = getattr(self, campo)
            if valor is not None:
                setattr(self, campo, valor.upper())

    def clean(self):
        super().clean()
        self.normalizar_mayusculas()
        dia, mes = self.dia_nacimiento, self.mes_nacimiento
        if (dia is None) != (mes is None):
            raise ValidationError({"dia_nacimiento": "Indica tanto el día como el mes de nacimiento."})
        if dia is not None and mes is not None:
            try:
                date(2000, mes, dia)
            except (ValueError, TypeError):
                raise ValidationError({"dia_nacimiento": "El día no es válido para el mes seleccionado."})

    def save(self, *args, **kwargs):
        self.normalizar_mayusculas()
        super().save(*args, **kwargs)
