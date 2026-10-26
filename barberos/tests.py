from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from horarios.models import Silla, Horario
from .models import Barbero
from .forms import BarberoForm


class PrestadoresSillasTests(TestCase):
    def setUp(self):
        self.silla=Silla.objects.create(nombre='Silla para masajes con nombre largo')
        self.user=get_user_model().objects.create_user(username='prueba',password='clave-prueba')
        self.client.force_login(self.user)

    def datos(self,**cambios):
        d={'codigo':'PS01','nombre':'Ana','apellido':'Pérez','direccion':'Dirección',
           'telefono':'12345','correo':'','fecha_ingreso':'2026-10-18',
           'porcentaje':'50.00','silla':self.silla.pk,'activo':'on'}
        d.update(cambios);return d

    def guardar(self,**cambios):
        f=BarberoForm(self.datos(**cambios));self.assertTrue(f.is_valid(),f.errors);return f.save()

    def test_guarda_relacion_y_nombre_largo(self):
        objeto=self.guardar()
        self.assertEqual(objeto.silla,self.silla)
        self.assertIsNone(objeto.codigo_silla)

    def test_silla_obligatoria_y_rechaza_id_inexistente(self):
        for silla in ['',9999]:
            with self.subTest(silla=silla):self.assertFalse(BarberoForm(self.datos(silla=silla)).is_valid())

    def test_inactiva_solo_se_conserva_en_edicion(self):
        objeto=self.guardar();self.silla.activa=False;self.silla.save()
        self.assertFalse(BarberoForm(self.datos(codigo='PS02')).is_valid())
        f=BarberoForm(self.datos(),instance=objeto);self.assertTrue(f.is_valid(),f.errors)

    def test_silla_utilizada_no_se_elimina(self):
        self.guardar()
        with self.assertRaises(ProtectedError):self.silla.delete()
        respuesta=self.client.post(reverse('horarios:eliminar_silla',args=[self.silla.pk]))
        self.assertEqual(respuesta.status_code,302)
        self.assertTrue(Silla.objects.filter(pk=self.silla.pk).exists())

    def test_busqueda_por_silla_y_acceso_desde_prestadores(self):
        self.guardar()
        respuesta=self.client.get(reverse('barberos:lista_barberos'),{'buscar':'masajes'})
        self.assertContains(respuesta,'Ana')
        self.assertContains(respuesta,'Administrar sillas')
        self.assertContains(respuesta,reverse('horarios:listar_sillas'))

    def test_pantallas_y_formulario_desplegable(self):
        objeto=self.guardar()
        for route,args in [('barberos:lista_barberos',[]),('barberos:crear_barbero',[]),
            ('barberos:editar_barbero',[objeto.pk]),('barberos:detalle_barbero',[objeto.pk]),
            ('horarios:listar_sillas',[]),('horarios:crear_silla',[]),('horarios:editar_silla',[self.silla.pk])]:
            with self.subTest(route=route):
                respuesta=self.client.get(reverse(route,args=args))
                self.assertEqual(respuesta.status_code,200)
        self.assertContains(self.client.get(reverse('barberos:crear_barbero')),'name="silla"')
        self.assertContains(self.client.get(reverse('horarios:listar_sillas')),reverse('barberos:lista_barberos'))

    def test_asociacion_automatica_conserva_no_coincidentes(self):
        a=Barbero.objects.create(codigo='A',nombre='Ana',apellido='A',direccion='a',telefono='1',
            fecha_ingreso=date.today(),porcentaje=Decimal('50'),codigo_silla=' S01 ')
        b=Barbero.objects.create(codigo='B',nombre='Ana',apellido='B',direccion='a',telefono='1',
            fecha_ingreso=date.today(),porcentaje=Decimal('50'),codigo_silla='vieja')
        silla=Silla.objects.create(nombre='s01')
        m=import_module('barberos.migrations.0003_asociar_sillas_anteriores')
        m.asociar_sillas(apps,SimpleNamespace(connection=SimpleNamespace(alias='default')))
        a.refresh_from_db();b.refresh_from_db()
        self.assertEqual(a.silla_id,silla.pk);self.assertIsNone(b.silla_id)
        self.assertEqual(b.codigo_silla,'vieja')

    def test_filtro_horarios_conserva_nombre_interno(self):
        respuesta=self.client.get(reverse('horarios:listar_horarios'))
        self.assertContains(respuesta,'name="barbero"')
        self.assertNotContains(respuesta,'name="prestador de servicio"')

    def test_comision_fuera_de_rango(self):
        for valor in ['-1','101']:
            self.assertFalse(BarberoForm(self.datos(porcentaje=valor)).is_valid())
