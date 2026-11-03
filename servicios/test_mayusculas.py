from datetime import date
from django.test import TestCase
from barberos.forms import BarberoForm
from barberos.models import Barbero
from horarios.models import Silla
from servicios.forms import ServicioForm
from servicios.models import Servicio


class MayusculasTests(TestCase):
    def test_prestador_formulario_y_guardado(self):
        silla = Silla.objects.create(nombre='Silla')
        f = BarberoForm({'codigo': 'ps01', 'nombre': 'maría', 'apellido': 'pérez',
                         'direccion': 'calle sur', 'telefono': '12345', 'correo': 'maria@example.com',
                         'fecha_ingreso': '2026-10-01', 'porcentaje': '50', 'silla': silla.pk})
        self.assertTrue(f.is_valid(), f.errors)
        obj = f.save()
        obj.refresh_from_db()
        self.assertEqual((obj.codigo, obj.nombre, obj.apellido, obj.direccion, obj.correo),
                         ('PS01', 'MARÍA', 'PÉREZ', 'CALLE SUR', 'MARIA@EXAMPLE.COM'))
        directo = Barbero.objects.create(codigo='ps02', nombre='ana', apellido='paz', direccion='sur',
                                          telefono='1', fecha_ingreso=date(2026, 10, 1), porcentaje=0)
        self.assertEqual((directo.codigo, directo.nombre), ('PS02', 'ANA'))

    def test_servicio_formulario_y_guardado(self):
        f = ServicioForm({'codigo': 'ser1', 'nombre': 'corte', 'descripcion': 'cabello corto',
                          'modo_precio': 'automatico', 'precio': '10', 'duracion': '30'})
        self.assertTrue(f.is_valid(), f.errors)
        obj = f.save()
        obj.refresh_from_db()
        self.assertEqual((obj.codigo, obj.nombre, obj.descripcion), ('SER1', 'CORTE', 'CABELLO CORTO'))
        directo = Servicio.objects.create(codigo='ser2', nombre='barba', descripcion='afeitado',
                                           precio=10, duracion=20)
        self.assertEqual((directo.codigo, directo.nombre, directo.descripcion), ('SER2', 'BARBA', 'AFEITADO'))
