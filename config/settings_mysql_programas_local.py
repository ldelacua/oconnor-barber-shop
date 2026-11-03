"""Perfil de evaluación local. Nunca apunta a la base de la aplicación habitual."""
from .settings_mysql import *
from django.core.exceptions import ImproperlyConfigured

BASE_EXPERIMENTAL = 'barberia_validacion_programas'
if DATABASES['default']['HOST'] not in {'localhost', '127.0.0.1', '::1'}:
    raise ImproperlyConfigured('El perfil experimental solo admite MySQL local.')
if DATABASES['default']['NAME'].lower() == BASE_EXPERIMENTAL:
    raise ImproperlyConfigured('La configuración habitual no debe usar la base experimental.')
DATABASES['default'] = dict(DATABASES['default'])
DATABASES['default']['NAME'] = BASE_EXPERIMENTAL
MIGRATION_MODULES = dict(MIGRATION_MODULES)
MIGRATION_MODULES['mysql_nuevo'] = 'mysql_nuevo.esquema_programas_pruebas'
