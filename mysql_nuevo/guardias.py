"""Protecciones de mutaciones realizadas mediante los modelos Django.

No protegen accesos directos a la base ni sustituyen los disparadores.
"""
from contextlib import contextmanager
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction


@contextmanager
def mutacion_serializada(queryset):
    if queryset.db != 'default':
        raise ValidationError('La operación debe usar la conexión principal.')
    with transaction.atomic(using=queryset.db):
        from .bloqueos import serializar_operacion
        serializar_operacion()
        yield


class BloquearFinalizadosQuerySet(models.QuerySet):
    criterio_finalizado = {}
    mensaje = 'El registro finalizado no se puede modificar.'

    def comprobar_no_finalizado(self):
        if self.filter(**self.criterio_finalizado).exists():
            raise IntegrityError(self.mensaje)

    def update(self, **kwargs):
        with mutacion_serializada(self):
            self.comprobar_no_finalizado()
            return super().update(**kwargs)

    def delete(self):
        with mutacion_serializada(self):
            self.comprobar_no_finalizado()
            return super().delete()

    def bulk_create(self, *args, **kwargs):
        raise IntegrityError('Utiliza el formulario para crear los registros.')


def guardar_serializado(funcion):
    """Serializa la comprobación y la escritura de una instancia de Django."""
    @wraps(funcion)
    def protegido(instancia, *args, **kwargs):
        alias = kwargs.get('using') or instancia._state.db or 'default'
        if alias != 'default':
            raise ValidationError('La operación debe usar la conexión principal.')
        with transaction.atomic(using=alias):
            from .bloqueos import serializar_operacion
            serializar_operacion()
            return funcion(instancia, *args, **kwargs)
    return protegido
