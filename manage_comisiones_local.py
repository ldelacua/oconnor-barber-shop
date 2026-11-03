"""Inicializa y abre solo la base local aislada de comisiones."""
import os
import sys

BASE = 'barberia_comisiones_prueba'
if __name__ == '__main__':
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_mysql_comisiones_local'
    admitidos = {'preparar_base', 'migrate', 'actualizar_base', 'verificar', 'runserver', 'createsuperuser', 'crear_grupos_barberia'}
    if len(sys.argv) < 2 or sys.argv[1] not in admitidos:
        raise SystemExit('Comando no permitido en esta prueba local.')
    import django
    django.setup()
    from django.core.exceptions import ImproperlyConfigured
    from django.core.management.base import CommandError
    from django.db import DatabaseError, connection, connections
    from mysql_nuevo import preparar_programas_local as preparacion
    from mysql_nuevo import verificacion_programas_local as verificacion
    preparacion.BASE = BASE
    verificacion.BASE = BASE
    try:
        actualizacion = sys.argv[1] == 'actualizar_base'
        if actualizacion:
            if len(sys.argv) != 2:
                raise CommandError('La actualización no admite opciones.')
            if connection.settings_dict['NAME'] != BASE or connection.settings_dict['HOST'] not in {'localhost','127.0.0.1','::1'}:
                raise CommandError('La actualización solo admite la base local aislada de comisiones.')
            with connection.cursor() as cursor:
                cursor.execute('SELECT DATABASE()')
                if cursor.fetchone()[0] != BASE:
                    raise CommandError('La conexión no coincide con la base de prueba.')
                cursor.execute('SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()')
                if cursor.fetchone()[0]:
                    raise CommandError('La prueba debe estar configurada sin disparadores.')
                cursor.execute('SELECT app,name FROM django_migrations')
                aplicadas = set(cursor.fetchall())
                requeridas = {('mysql_nuevo','0002_protecciones'),('liquidaciones','0003_protecciones_comision'),('ventas_productos','0004_permisos_comision')}
                if not requeridas.issubset(aplicadas):
                    raise CommandError('La base no coincide con la prueba de comisiones ya inicializada.')
            sys.argv[1] = 'migrate'
        if sys.argv[1] == 'preparar_base':
            if len(sys.argv) != 2:
                raise CommandError('No se admiten opciones para preparar la base.')
            creada = preparacion.preparar()
            print('Base de prueba creada.' if creada else 'La base de prueba ya existe y está vacía.')
            sys.exit(0)
        if sys.argv[1] == 'migrate':
            if len(sys.argv) != 2:
                raise CommandError('La migración inicial no admite opciones.')
            with connection.cursor() as cursor:
                cursor.execute('SELECT DATABASE()')
                if cursor.fetchone()[0] != BASE:
                    raise CommandError('La conexión no apunta a la base de prueba.')
                cursor.execute('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
                if cursor.fetchone()[0] and not actualizacion:
                    raise CommandError('La base no está vacía; no se ejecutó la migración.')
        else:
            if sys.argv[1] == 'runserver':
                if len(sys.argv) == 2:
                    sys.argv.append('8003')
                elif sys.argv[2:] not in (['8003'], ['127.0.0.1:8003']):
                    raise CommandError('Usa runserver 8003 solo desde esta computadora.')
            numero = verificacion.comprobar(connection)
            print(f'Base de comisiones verificada: {numero} tablas y 0 disparadores.')
            if sys.argv[1] == 'verificar':
                sys.exit(0)
    except (ImproperlyConfigured, CommandError, DatabaseError) as error:
        raise SystemExit('No se pudo preparar o verificar la base de prueba: ' + str(error))
    finally:
        connections.close_all()
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
