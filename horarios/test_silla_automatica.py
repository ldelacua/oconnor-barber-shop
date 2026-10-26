import json
from datetime import date, time
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from barberos.models import Barbero
from .models import Silla, Horario
from .forms import MatrizHorarioForm, HorarioForm


class SillaAutomaticaTests(TestCase):
    def setUp(self):
        self.silla=Silla.objects.create(nombre='Silla A')
        self.otra=Silla.objects.create(nombre='Silla B')
        self.prestador=Barbero.objects.create(codigo='PS1',nombre='Ana',apellido='Pérez',
            direccion='a',telefono='1',fecha_ingreso=date.today(),porcentaje=50,silla=self.silla)
        self.client.force_login(get_user_model().objects.create_user(username='ana',password='clave-prueba'))

    def datos(self, **cambios):
        d={'barbero':self.prestador.pk,'bloques':json.dumps({'1':['08:00']}),'activo':'on'}
        d.update(cambios);return d

    def test_matriz_omite_silla_y_guarda_asignada(self):
        f=MatrizHorarioForm(self.datos())
        self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.cleaned_data['silla'],self.silla)

    def test_silla_falsificada_se_ignora(self):
        f=MatrizHorarioForm(self.datos(silla=self.otra.pk))
        self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.cleaned_data['silla'],self.silla)

    def test_sin_silla_no_guarda(self):
        self.prestador.silla=None;self.prestador.save()
        f=MatrizHorarioForm(self.datos())
        self.assertFalse(f.is_valid());self.assertIn('barbero',f.errors)

    def test_silla_inactiva_no_guarda(self):
        self.silla.activa=False;self.silla.save()
        f=MatrizHorarioForm(self.datos())
        self.assertFalse(f.is_valid());self.assertIn('barbero',f.errors)

    def test_editar_toma_silla_del_prestador(self):
        h=Horario.objects.create(barbero=self.prestador,silla=self.otra,dia_semana=1,hora_inicio=time(8),hora_fin=time(9),activo=True)
        d={'barbero':self.prestador.pk,'silla':self.otra.pk,'dia_semana':1,'hora_inicio':'08:00','hora_fin':'09:00','activo':'on'}
        f=HorarioForm(d,instance=h)
        self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.save().silla_id,self.silla.pk)

    def test_conserva_validacion_solapamiento(self):
        Horario.objects.create(barbero=self.prestador,silla=self.silla,dia_semana=1,hora_inicio=time(8),hora_fin=time(9),activo=True)
        d={'barbero':self.prestador.pk,'dia_semana':1,'hora_inicio':'08:30','hora_fin':'09:30','activo':'on'}
        f=HorarioForm(d)
        self.assertFalse(f.is_valid());self.assertTrue('silla' in f.errors or 'barbero' in f.errors)

    def test_formulario_muestra_silla_solo_lectura(self):
        response=self.client.get(reverse('horarios:crear_horario'),{'barbero':self.prestador.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'silla-asignada-nombre')
        self.assertContains(response,'Silla A')
        self.assertNotContains(response,'<select name="silla"')

    def test_vista_guarda_matriz_sin_enviar_silla(self):
        pagina=self.client.get(reverse('horarios:crear_horario'),{'barbero':self.prestador.pk})
        revision=pagina.context['formulario']['revision'].value()
        response=self.client.post(reverse('horarios:crear_horario'),{**self.datos(silla=self.otra.pk),'revision':revision})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Horario.objects.exists())
        self.assertEqual(Horario.objects.first().silla_id,self.silla.pk)
