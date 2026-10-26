"""Orden único de bloqueo para documentos, existencias, cierres y comisiones."""
from django.core.exceptions import ImproperlyConfigured
from django.db import connection


def serializar_operacion():
    if connection.vendor!='mysql':return
    if not connection.in_atomic_block:
        raise ImproperlyConfigured('Una operación financiera MySQL debe ejecutarse dentro de transaction.atomic().')
    with connection.cursor() as cursor:
        cursor.execute('SELECT id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE')
        if cursor.fetchone() is None:
            raise ImproperlyConfigured('Falta inicializar el candado de operaciones de MySQL. Ejecuta migrate con config.settings_mysql.')


def mutacion_mysql(funcion):
    """Serializa validación y guardado de formularios POST que consultan agenda."""
    from functools import wraps
    from django.db import transaction
    @wraps(funcion)
    def protegida(request,*args,**kwargs):
        if connection.vendor!='mysql' or request.method!='POST':
            return funcion(request,*args,**kwargs)
        with transaction.atomic():
            serializar_operacion()
            return funcion(request,*args,**kwargs)
    return protegida


def es_error_transitorio(error):
    return bool(error.args and error.args[0] in {1205,1213,3572}) or 'locked' in str(error).lower()
