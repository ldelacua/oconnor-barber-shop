#!/usr/bin/env python
import os
import sys

if __name__=='__main__':
    os.environ['DJANGO_SETTINGS_MODULE']='config.settings_mysql'
    if len(sys.argv)>1 and sys.argv[1]=='runserver':
        import django
        django.setup()
        from django.core.management import call_command,CommandError
        from django.db import connections,DatabaseError
        try:
            call_command('verificar_mysql')
        except (CommandError,DatabaseError) as error:
            raise SystemExit('MySQL no está preparado para iniciar: '+str(error))
        finally:
            connections.close_all()
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
