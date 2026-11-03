from django.test import TestCase
from django.utils import timezone
from ventas.forms import VentaForm
from ventas_productos.forms import CabeceraForm


class FechaVentaTests(TestCase):
    def test_ignora_fecha_enviada_por_el_cliente(self):
        for clase in (VentaForm, CabeceraForm):
            with self.subTest(formulario=clase.__name__):
                form = clase({'fecha': '2000-01-01'})
                form.is_valid()
                self.assertTrue(form.fields['fecha'].disabled)
                self.assertEqual(form.cleaned_data['fecha'], timezone.localdate())
