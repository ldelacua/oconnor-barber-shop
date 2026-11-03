"""Perfil aislado y local para comprobar comisiones de productos."""
from .settings_mysql import *
from django.core.exceptions import ImproperlyConfigured

BASE_COMISIONES = 'barberia_comisiones_prueba'
if DATABASES['default']['HOST'] not in {'localhost', '127.0.0.1', '::1'}:
    raise ImproperlyConfigured('La prueba de comisiones requiere MySQL local.')
if DATABASES['default']['NAME'].lower() == BASE_COMISIONES:
    raise ImproperlyConfigured('La configuración habitual no debe usar la base de prueba.')
DATABASES['default'] = dict(DATABASES['default'])
DATABASES['default']['NAME'] = BASE_COMISIONES
MIGRATION_MODULES = dict(MIGRATION_MODULES)
MIGRATION_MODULES['mysql_nuevo'] = 'mysql_nuevo.esquema_programas_pruebas'
