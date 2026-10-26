"""Perfil MySQL NUEVO. No reutiliza ni modifica la base SQLite."""
from .settings import *
from pathlib import Path
import os
import json
from django.core.exceptions import ImproperlyConfigured
from mysql_nuevo.perfil import MIGRACIONES

ruta=Path(os.environ.get('MYSQL_CONFIG_PATH',BASE_DIR/'mysql.local.json'))
try:
    local=json.loads(ruta.read_text(encoding='utf-8')) if ruta.is_file() else {}
except (ValueError,OSError) as error:
    raise ImproperlyConfigured('No se pudo leer la configuración local de MySQL.') from error

def valor(nombre,defecto=''):
    return os.environ.get('MYSQL_'+nombre,local.get(nombre.lower(),defecto))

nombre=valor('DATABASE');usuario=valor('USER');clave=valor('PASSWORD')
if not nombre or not usuario or not clave:
    raise ImproperlyConfigured('Configura MySQL con configurar_mysql.py antes de utilizar manage_mysql.py.')
INSTALLED_APPS=list(INSTALLED_APPS)+['mysql_nuevo']
MIGRATION_MODULES=dict(MIGRACIONES)
DATABASES={'default':{
    'ENGINE':'django.db.backends.mysql','NAME':nombre,'USER':usuario,'PASSWORD':clave,
    'HOST':valor('HOST','127.0.0.1'),'PORT':str(valor('PORT','3306')),
    'CONN_MAX_AGE':60,
    'OPTIONS':{'charset':'utf8mb4','isolation_level':'read committed','connect_timeout':10,
       'init_command':"SET default_storage_engine='InnoDB', sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'"},
    'TEST':{'NAME':valor('TEST_DATABASE','test_'+nombre)},
}}
# MySQL no admite índices parciales. Se sustituyen por índices de columnas
# generadas y se comprueba expresamente que existan en verificar_mysql.
SILENCED_SYSTEM_CHECKS=list(globals().get('SILENCED_SYSTEM_CHECKS',[]))+['models.W036']
