"""Pruebas en una base temporal con nombre aleatorio, separada de barberia."""
import os
import sys
import uuid
from pathlib import Path

if __name__=='__main__':
    if not (Path(__file__).resolve().parent/'mysql.local.json').exists() and not os.environ.get('MYSQL_DATABASE'):
        raise SystemExit('Primero ejecuta configurar_mysql.py.')
    temporal='verificacion_barberia_'+uuid.uuid4().hex[:12]
    os.environ['MYSQL_TEST_DATABASE']=temporal
    os.environ['DJANGO_SETTINGS_MODULE']='config.settings_mysql'
    print('Las pruebas usarán únicamente la base temporal '+temporal+'.')
    print('El usuario MySQL necesita poder crear y eliminar esta base de pruebas y crear disparadores.')
    from django.core.management import execute_from_command_line
    etiquetas=['seguridad','ventas','servicios','inventario','ventas_productos','control_inventario',
               'autenticacion.test_cumpleaneros','mysql_nuevo.test_conversion','mysql_nuevo.test_integracion']
    execute_from_command_line([sys.argv[0],'test',*etiquetas,'--noinput','--verbosity','1'])
