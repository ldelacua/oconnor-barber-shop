from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Crea los grupos iniciales sin modificar usuarios ni grupos existentes.'

    @transaction.atomic
    def handle(self, *args, **options):
        nombres = ('ADMINISTRADOR', 'ENCARGADO', 'PRESTADOR DE SERVICIO')
        existentes = list(Group.objects.filter(name__in=nombres).values_list('name', flat=True))
        if existentes:
            raise CommandError('Ya existen estos grupos: ' + ', '.join(existentes) + '. No se modificó ningún grupo; revisa sus permisos antes de continuar.')
        administrador = Group.objects.create(name=nombres[0])
        administrador.permissions.set(Permission.objects.all())
        encargado = Group.objects.create(name=nombres[1])
        apps = ('clientes', 'barberos', 'servicios', 'horarios', 'citas', 'tasas_bcv',
                'ventas', 'liquidaciones', 'gastos', 'inventario', 'ventas_productos')
        encargado.permissions.set(Permission.objects.filter(content_type__app_label__in=apps))
        # Las consultas propias se autorizan por la cuenta vinculada, no mediante
        # permisos generales que permitirían acceder a registros de terceros.
        Group.objects.create(name=nombres[2])
        self.stdout.write(self.style.SUCCESS('Grupos creados. Asigna cada usuario y vincula cada prestador desde Administración.'))
        self.stdout.write('El acceso completo a la administración de usuarios y grupos requiere un superusuario.')
