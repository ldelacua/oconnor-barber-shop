"""Prepara solo una base local experimental nueva o existente y vacía."""
from django.core.exceptions import ImproperlyConfigured
from django.db import connections

BASE = 'barberia_validacion_programas'

def preparar():
    conexion = connections['default']
    if (conexion.vendor != 'mysql' or conexion.settings_dict['NAME'] != BASE
        or conexion.settings_dict['HOST'] not in {'127.0.0.1', 'localhost', '::1'}):
        raise ImproperlyConfigured('Se rechazó preparar una base que no es la experimental local.')
    with conexion._nodb_cursor() as cursor:
        cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', [BASE])
        existe = cursor.fetchone() is not None
        if existe:
            cursor.execute('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s', [BASE])
            if cursor.fetchone()[0]:
                raise ImproperlyConfigured('La base experimental ya contiene tablas o vistas; no se modificó.')
            return False
        nombre = conexion.ops.quote_name(BASE)
        cursor.execute('CREATE DATABASE ' + nombre + ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        return True
