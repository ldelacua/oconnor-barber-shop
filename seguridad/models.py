from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    telefono = models.CharField(max_length=20, blank=True)
    prestador = models.OneToOneField('barberos.Barbero', on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='cuenta_usuario', verbose_name='Prestador de servicio')

    @property
    def es_prestador_restringido(self):
        return not self.is_superuser and (self.prestador_id is not None or self.groups.filter(name='PRESTADOR DE SERVICIO').exists())

    def __str__(self):
        return self.username


class Auditoria(models.Model):
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    accion = models.CharField(max_length=50)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario} - {self.accion}"
