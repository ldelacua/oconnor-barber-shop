from datetime import time
from io import StringIO
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.urls import reverse
from citas.models import Cita
from ventas import test_iva_incluido as base
from barberos.models import Barbero


class RolesPropiosTests(TestCase):
    setUp = base.VentaIvaIncluidoTests.setUp
    vender = base.VentaIvaIncluidoTests.vender
    pago = base.VentaIvaIncluidoTests.pago
    liquidar = base.VentaIvaIncluidoTests.liquidar

    def test_grupos_se_crean_sin_control_y_no_sobrescriben(self):
        call_command('crear_grupos_barberia', stdout=StringIO())
        encargado = Group.objects.get(name='ENCARGADO')
        self.assertTrue(encargado.permissions.filter(content_type__app_label='ventas', codename='add_documentoventa').exists())
        self.assertFalse(encargado.permissions.filter(content_type__app_label='control_inventario').exists())
        self.assertFalse(encargado.permissions.filter(content_type__app_label='seguridad').exists())
        self.assertTrue(Group.objects.get(name='ADMINISTRADOR').permissions.filter(content_type__app_label='control_inventario').exists())
        self.assertFalse(Group.objects.get(name='PRESTADOR DE SERVICIO').permissions.exists())
        usuario = get_user_model().objects.create_user(username='encargado', password='clave-segura')
        usuario.groups.add(encargado)
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(reverse('ventas:lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('control_inventario:stock')).status_code, 403)
        with self.assertRaises(CommandError):
            call_command('crear_grupos_barberia', stdout=StringIO())
        self.assertEqual(Group.objects.count(), 3)

    def test_prestador_solo_ve_sus_documentos_incluso_con_otros_permisos(self):
        primer_prestador = self.prestador
        primera_venta = self.vender()
        primera_liquidacion = self.liquidar(primera_venta, '58')
        otro = Barbero.objects.create(codigo='OTRO', nombre='OTRO', apellido='BARBERO', direccion='A', telefono='1', fecha_ingreso=self.fecha, porcentaje=50)
        self.prestador = otro
        segunda_venta = self.vender()
        segunda_liquidacion = self.liquidar(segunda_venta, '58')
        Cita.objects.create(cliente=self.cliente, barbero=primer_prestador, servicio=self.servicio, fecha=self.fecha, hora=time(9), observaciones='CITA PROPIA')
        otro_cliente = type(self.cliente).objects.create(nombre='CLIENTE SECRETO', apellido='AJENO', telefono='123')
        Cita.objects.create(cliente=otro_cliente, barbero=otro, servicio=self.servicio, fecha=self.fecha, hora=time(10), observaciones='CITA AJENA')
        grupo = Group.objects.create(name='PRESTADOR DE SERVICIO')
        usuario = get_user_model().objects.create_user(username='barbero1', password='clave-segura', prestador=primer_prestador, is_staff=True)
        usuario.groups.add(grupo)
        usuario.user_permissions.add(Permission.objects.get(content_type__app_label='ventas', codename='view_documentoventa'))
        self.client.force_login(usuario)
        r = self.client.get(reverse('mis_citas'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.cliente.nombre)
        self.assertNotContains(r, 'CLIENTE SECRETO')
        r = self.client.get(reverse('mis_liquidaciones'))
        self.assertContains(r, str(primera_liquidacion))
        self.assertNotContains(r, str(segunda_liquidacion))
        self.assertEqual(self.client.get(reverse('mi_liquidacion', args=[primera_liquidacion.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('mi_liquidacion', args=[segunda_liquidacion.pk])).status_code, 404)
        for url in ('citas:listar_citas', 'citas:agenda_citas', 'liquidaciones:lista', 'ventas:lista', 'admin:index'):
            self.assertEqual(self.client.get(reverse(url)).status_code, 403, url)
        self.assertEqual(self.client.get(reverse('cambiar_clave')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        grupo.name = 'CAMBIADO'
        grupo.save()
        self.assertEqual(self.client.get(reverse('ventas:lista')).status_code, 403)

    def test_prestador_sin_vinculo_no_obtiene_datos(self):
        grupo = Group.objects.create(name='PRESTADOR DE SERVICIO')
        usuario = get_user_model().objects.create_user(username='sin_prestador', password='clave-segura')
        usuario.groups.add(grupo)
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(reverse('mis_citas')).status_code, 403)
        self.assertEqual(self.client.get(reverse('mis_liquidaciones')).status_code, 403)
