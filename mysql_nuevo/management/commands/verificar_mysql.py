from django.core.management.base import BaseCommand
from django.db import connection
from mysql_nuevo.verificacion import comprobar

class Command(BaseCommand):
    help='Comprueba motor, aislamiento, vista de stock, bloqueos y 57 disparadores.'
    def handle(self,*args,**options):
        datos=comprobar(connection)
        self.stdout.write(self.style.SUCCESS(f"MySQL 8.4 OK: {datos['tablas']} tablas InnoDB, {datos['disparadores']} disparadores, vista de stock y restricciones especiales instaladas."))
