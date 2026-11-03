"""Arranque de la copia experimental local, en una base separada."""
import os
import sys

if __name__ == '__main__':
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_mysql_programas_local'
    if len(sys.argv) > 1 and sys.argv[1] in {'preparar_base', 'verificar', 'migrate', 'runserver'}:
        import django
        django.setup()
        from django.core.exceptions import ImproperlyConfigured
        from django.core.management.base import CommandError
        from django.db import DatabaseError, connection, connections
        try:
            if sys.argv[1] == 'preparar_base':
                from mysql_nuevo.preparar_programas_local import preparar
                creada = preparar()
                print('Base experimental creada.' if creada else 'La base experimental ya existe y está vacía.')
                print('Siguiente paso: python manage_programas_local.py migrate')
                sys.exit(0)
            if sys.argv[1] == 'migrate':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT DATABASE()')
                    if cursor.fetchone()[0] != 'barberia_validacion_programas':
                        raise CommandError('La conexión no apunta a la base experimental.')
                    cursor.execute('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
                    if cursor.fetchone()[0]:
                        raise CommandError('La base experimental no está vacía. No se modificó; solicita una revisión antes de continuar.')
                if len(sys.argv) != 2:
                    raise CommandError('La inicialización experimental no acepta opciones ni migraciones parciales.')
            else:
                if sys.argv[1] == 'runserver':
                    if len(sys.argv) == 2:
                        sys.argv.append('8002')
                    elif sys.argv[2:] not in (['8002'], ['127.0.0.1:8002']):
                        raise CommandError('Usa runserver 8002 para acceder solo desde esta computadora.')
                from mysql_nuevo.verificacion_programas_local import comprobar
                numero = comprobar(connection)
            if sys.argv[1] != 'migrate':
                print(f'Infraestructura experimental verificada: {numero} tablas y 0 disparadores.')
                print('Prueba local únicamente; SQL directo no está protegido y la evaluación no está completa.')
                if sys.argv[1] == 'verificar':
                    sys.exit(0)
        except (ImproperlyConfigured, CommandError, DatabaseError) as error:
            raise SystemExit('No se pudo preparar o verificar la base experimental: ' + str(error))
        finally:
            connections.close_all()
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
