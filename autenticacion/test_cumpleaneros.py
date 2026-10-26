from datetime import date
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.urls import reverse
from clientes.models import Cliente


class CumpleanerosTests(TestCase):
    def setUp(self):
        self.usuario=get_user_model().objects.create_user(username='cumple',password='prueba')
        self.client.force_login(self.usuario)
        self.permiso=Permission.objects.get(content_type__app_label='clientes',codename='view_cliente')

    def cliente(self,nombre,dia=25,mes=10,**otros):
        return Cliente.objects.create(nombre=nombre,apellido='CLIENTE',telefono='04121234567',dia_nacimiento=dia,mes_nacimiento=mes,**otros)

    def consultar(self,fecha=date(2026,10,25)):
        with patch('autenticacion.views.timezone.localdate',return_value=fecha):
            return self.client.get(reverse('dashboard'))

    def test_solo_dia_mes_activo_y_orden(self):
        self.usuario.user_permissions.add(self.permiso)
        z=self.cliente('ZULEIMA');a=self.cliente('ANA')
        self.cliente('OTRO DIA',dia=24);self.cliente('OTRO MES',mes=9)
        self.cliente('INACTIVO',activo=False);self.cliente('SIN FECHA',dia=None,mes=None)
        r=self.consultar()
        self.assertEqual([c.pk for c in r.context['cumpleaneros']],[a.pk,z.pk])
        self.assertContains(r,'Cumpleañeros del día');self.assertContains(r,'25/10/2026')
        self.assertContains(r,'04121234567')
        self.assertContains(r,reverse('clientes:detalle_cliente',args=[a.pk]))

    def test_no_consulta_ni_expone_clientes_sin_permiso(self):
        self.cliente('PRIVADO')
        r=self.consultar()
        self.assertEqual(r.context['cumpleaneros'],[])
        self.assertNotContains(r,'Cumpleañeros del día');self.assertNotContains(r,'PRIVADO')

    def test_permiso_por_grupo(self):
        g=Group.objects.create(name='Consulta clientes');g.permissions.add(self.permiso);self.usuario.groups.add(g)
        c=self.cliente('POR GRUPO')
        self.assertEqual([x.pk for x in self.consultar().context['cumpleaneros']],[c.pk])

    def test_estado_vacio(self):
        self.usuario.user_permissions.add(self.permiso)
        self.assertContains(self.consultar(),'No hay clientes activos que cumplan años hoy.')

    def test_fecha_historica_no_reemplaza_dia_mes(self):
        self.usuario.user_permissions.add(self.permiso)
        self.cliente('FECHA ACTUAL',fecha_nacimiento=date(1980,1,1))
        self.cliente('HISTORICO',dia=None,mes=None,fecha_nacimiento=date(1980,10,25))
        self.assertEqual([c.nombre for c in self.consultar().context['cumpleaneros']],['FECHA ACTUAL'])

    def test_cambio_de_mes_y_29_febrero(self):
        self.usuario.user_permissions.add(self.permiso)
        c=self.cliente('BISIESTO',dia=29,mes=2)
        self.assertEqual([x.pk for x in self.consultar(date(2028,2,29)).context['cumpleaneros']],[c.pk])
        self.assertEqual(self.consultar(date(2027,2,28)).context['cumpleaneros'],[])
        self.assertEqual(self.consultar(date(2028,3,1)).context['cumpleaneros'],[])

    def test_superusuario(self):
        self.usuario.is_superuser=True;self.usuario.save();self.cliente('SUPER')
        self.assertContains(self.consultar(),'SUPER CLIENTE')
