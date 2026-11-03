"""EXPERIMENTO: solo crea una base de pruebas temporal; no sirve para producción."""
from .settings_mysql import *
import os
import re
from django.core.exceptions import ImproperlyConfigured
nombre_prueba = os.environ.get('MYSQL_TEST_DATABASE', '')
if os.environ.get('MYSQL_PROGRAMAS_PRUEBAS') != '1' or not re.fullmatch(r'verificacion_barberia_[a-f0-9]{12}', nombre_prueba):
    raise ImproperlyConfigured('Este perfil solo funciona con pruebas_programas_mysql.py.')
if DATABASES['default']['HOST'] not in {'localhost', '127.0.0.1', '::1'}:
    raise ImproperlyConfigured('La prueba experimental requiere un servidor MySQL local.')
MIGRATION_MODULES = dict(MIGRATION_MODULES)
MIGRATION_MODULES['mysql_nuevo'] = 'mysql_nuevo.esquema_programas_pruebas'
DATABASES['default'] = dict(DATABASES['default'])
DATABASES['default']['NAME'] = nombre_prueba
DATABASES['default']['TEST'] = {'NAME': nombre_prueba}

TEST_RUNNER = "mysql_nuevo.runner_programas.RunnerProgramas"
