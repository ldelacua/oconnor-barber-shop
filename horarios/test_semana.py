import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from barberos.models import Barbero
from .models import Horario, Silla
from .services.semana import (
    configurar_rejilla, seleccion_actual, guardar_semana, version_semana, cubre_cita,
)


class SemanaUnificadaTests(TestCase):
    def setUp(self):
        self.silla=Silla.objects.create(nombre='Silla principal')
        self.prestador=Barbero.objects.create(codigo='PS1',nombre='Ana',apellido='Pérez',direccion='a',telefono='1',fecha_ingreso=date.today(),porcentaje=50,silla=self.silla)
        self.client.force_login(get_user_model().objects.create_user(username='ana',password='clave-prueba'))
        self.url=reverse('horarios:listar_horarios')

    def horario(self, inicio=time(8), fin=time(10), dia=1, **kw):
        return Horario.objects.create(barbero=self.prestador,silla=self.silla,dia_semana=dia,hora_inicio=inicio,hora_fin=fin,**kw)

    def version(self):
        self.prestador.refresh_from_db()
        return version_semana(self.prestador,list(Horario.objects.filter(barbero=self.prestador)))

    def guardar(self, seleccion, **kw):
        return guardar_semana(prestador_id=self.prestador.pk,seleccion=seleccion,version=kw.pop('version',self.version()),**kw)

    def respuesta(self):
        return self.client.get(self.url,{'barbero':self.prestador.pk})

    def post(self, seleccion, **kw):
        revision=self.respuesta().context['formulario']['revision'].value()
        return self.client.post(self.url,{'barbero':self.prestador.pk,'revision':revision,'bloques':json.dumps(seleccion),**kw})

    def test_carga_semana_y_silla_sin_solicitarla(self):
        self.horario()
        r=self.respuesta()
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.context['seleccion_guardada']['1'],['08:00','08:30','09:00','09:30'])
        self.assertContains(r,'Silla principal')
        self.assertNotContains(r,'<select name="silla"')

    def test_crea_y_no_duplica_al_repetir(self):
        s={'1':['08:00','08:30']}
        self.guardar(s);primero=Horario.objects.get()
        self.guardar(s)
        self.assertEqual(Horario.objects.count(),1)
        self.assertEqual(Horario.objects.get().pk,primero.pk)

    def test_no_cambia_id_ni_observaciones_si_no_hay_cambios(self):
        h=self.horario(observaciones='Nota anterior')
        self.guardar({'1':['08:00','08:30','09:00','09:30']},observaciones='Otra nota')
        h.refresh_from_db();self.assertTrue(h.activo);self.assertEqual(h.observaciones,'Nota anterior')

    def test_desmarcar_divide_y_conserva_historial(self):
        h=self.horario()
        self.guardar({'1':['08:00','09:00','09:30']})
        h.refresh_from_db();self.assertFalse(h.activo)
        rangos=list(Horario.objects.filter(activo=True).values_list('hora_inicio','hora_fin'))
        self.assertEqual(rangos,[(time(8),time(8,30)),(time(9),time(10))])

    def test_semana_vacia_desactiva_sin_borrar(self):
        h=self.horario();self.guardar({});h.refresh_from_db();self.assertFalse(h.activo)

    def test_reactiva_registro_identico(self):
        h=self.horario(activo=False)
        self.guardar({'1':['08:00','08:30','09:00','09:30']})
        h.refresh_from_db();self.assertTrue(h.activo);self.assertEqual(Horario.objects.count(),1)

    def test_conflicto_silla_no_modifica_nada(self):
        h=self.horario()
        otro=Barbero.objects.create(codigo='PS2',nombre='Otro',apellido='P',direccion='a',telefono='1',fecha_ingreso=date.today(),porcentaje=50,silla=self.silla)
        Horario.objects.create(barbero=otro,silla=self.silla,dia_semana=1,hora_inicio=time(10),hora_fin=time(11))
        with self.assertRaises(ValidationError):self.guardar({'1':['09:00','09:30','10:00']})
        h.refresh_from_db();self.assertTrue(h.activo);self.assertEqual(Horario.objects.count(),2)

    def test_revision_antigua_no_sobrescribe(self):
        h=self.horario();v=self.version()
        Horario.objects.filter(pk=h.pk).update(observaciones='Cambio de otra sesión')
        with self.assertRaisesMessage(ValidationError,'Recargar'):self.guardar({},version=v)
        h.refresh_from_db();self.assertTrue(h.activo)

    def test_sin_silla_o_inactiva_no_guarda(self):
        self.silla.activa=False;self.silla.save()
        with self.assertRaises(ValidationError):self.guardar({'1':['08:00']})
        self.prestador.silla=None;self.prestador.save()
        with self.assertRaises(ValidationError):self.guardar({})
        self.assertFalse(Horario.objects.exists())

    def test_cita_futura_impide_quitar_cualquier_parte(self):
        fecha=timezone.localdate()+timedelta(days=7)
        h=self.horario(inicio=time(10),fin=time(11),dia=fecha.isoweekday())
        cita=SimpleNamespace(pk=25,fecha=fecha,hora=time(10,15),duracion_total=30)
        with patch('horarios.services.semana._citas_futuras',return_value=[cita]):
            with self.assertRaisesMessage(ValidationError,'Cita 25'):
                self.guardar({str(fecha.isoweekday()):['10:00']})
        h.refresh_from_db();self.assertTrue(h.activo)

    def test_cita_conservada_permite_ampliacion(self):
        fecha=timezone.localdate()+timedelta(days=7)
        self.horario(inicio=time(10),fin=time(11),dia=fecha.isoweekday())
        cita=SimpleNamespace(pk=25,fecha=fecha,hora=time(10,15),duracion_total=30)
        with patch('horarios.services.semana._citas_futuras',return_value=[cita]):
            self.guardar({str(fecha.isoweekday()):['10:00','10:30','11:00']})
        self.assertEqual(Horario.objects.filter(activo=True).get().hora_fin,time(11,30))

    def test_cobertura_contigua_y_hueco(self):
        fecha=timezone.localdate()+timedelta(days=7);d=fecha.isoweekday()
        a=datetime.combine(fecha,time(10,15));b=a+timedelta(minutes=30)
        self.assertTrue(cubre_cita([(d,time(10),time(10,30)),(d,time(10,30),time(11))],a,b))
        self.assertFalse(cubre_cita([(d,time(10),time(10,30)),(d,time(10,45),time(11))],a,b))

    def test_rejilla_conserva_horarios_de_15_minutos(self):
        h=self.horario(inicio=time(8,15),fin=time(9,15))
        config=configurar_rejilla([h]);self.assertEqual(config['paso'],15)
        seleccion=seleccion_actual([h],config);self.guardar(seleccion)
        self.assertEqual(Horario.objects.count(),1)

    def test_rejilla_amplia_rango_antiguo(self):
        h=self.horario(inicio=time(7),fin=time(8))
        config=configurar_rejilla([h]);self.assertEqual(config['inicio'],420)
        self.guardar(seleccion_actual([h],config));self.assertEqual(Horario.objects.count(),1)

    def test_entradas_invalidas_no_modifican(self):
        h=self.horario()
        for s in [{'8':['08:00']},{'1':['99:00']},{'1':'08:00'},[],{'01':['08:00']}]:
            with self.subTest(s=s),self.assertRaises(ValidationError):self.guardar(s)
        h.refresh_from_db();self.assertTrue(h.activo)

    def test_post_firma_obligatoria_y_silla_falsificada_ignorada(self):
        r=self.client.post(self.url,{'barbero':self.prestador.pk,'bloques':'{"1":["08:00"]}'})
        self.assertEqual(r.status_code,200);self.assertFalse(Horario.objects.exists())
        r=self.post({'1':['08:00']},silla=999)
        self.assertEqual(r.status_code,302);self.assertEqual(Horario.objects.get().silla_id,self.silla.pk)

    def test_endpoints_antiguos_abren_matriz_sin_borrar(self):
        h=self.horario()
        for nombre in ['editar_horario','eliminar_horario','cambiar_estado_horario']:
            r=self.client.post(reverse('horarios:'+nombre,args=[h.pk]))
            self.assertEqual(r.status_code,302)
            self.assertIn('barbero='+str(self.prestador.pk),r.url)
        h.refresh_from_db();self.assertTrue(h.activo)

    def test_guardado_atomico_si_falla_segundo_bloque(self):
        h=self.horario();original=Horario.objects.create
        def crear(**datos):
            if datos['dia_semana']==2:raise ValidationError('Fallo de prueba')
            return original(**datos)
        with patch('horarios.services.semana.Horario.objects.create',side_effect=crear):
            with self.assertRaises(ValidationError):self.guardar({'1':['09:00'],'2':['08:00']})
        h.refresh_from_db();self.assertTrue(h.activo);self.assertEqual(Horario.objects.count(),1)
