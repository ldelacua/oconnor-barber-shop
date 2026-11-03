"""Prueba experimental aislada, no modifica la base local de la aplicación."""
import os
import sys
import uuid
from pathlib import Path
if __name__ == '__main__':
    if not (Path(__file__).resolve().parent/'mysql.local.json').exists() and not os.environ.get('MYSQL_DATABASE'):
        raise SystemExit('Falta configurar la conexión local a MySQL.')
    temporal = 'verificacion_barberia_' + uuid.uuid4().hex[:12]
    os.environ['MYSQL_TEST_DATABASE'] = temporal
    os.environ['MYSQL_PROGRAMAS_PRUEBAS'] = '1'
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_mysql_programas_pruebas'
    print('EXPERIMENTO: validación parcial sin disparadores, no apta para uso real.', flush=True)
    print('Se creará y eliminará únicamente la base temporal ' + temporal, flush=True)
    from django.core.management import execute_from_command_line
    etiquetas = [
        'seguridad', 'ventas', 'servicios', 'inventario', 'ventas_productos',
        'control_inventario', 'autenticacion.test_cumpleaneros',
        'mysql_nuevo.test_conversion', 'mysql_nuevo.test_integracion',
        'mysql_nuevo.test_programas_pruebas', 'mysql_nuevo.test_preparacion_programas',
    ]
    execute_from_command_line([sys.argv[0], 'test', *etiquetas, '--noinput', '--verbosity', '1'])
