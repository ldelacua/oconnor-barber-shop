from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from .comisiones import calcular_comision_periodo


class ComisionesPeriodoTests(SimpleTestCase):
    def test_escala_aplica_unidades_sumadas_y_base_neta(self):
        resultado = calcular_comision_periodo(
            [{'unidades': 6, 'base_usd': '18.00'}, {'unidades': 4, 'base_usd': '12.00'}],
            [{'unidades': 1, 'porcentaje': 5}, {'unidades': 10, 'porcentaje': 8}])
        self.assertEqual((resultado['unidades'], resultado['porcentaje'], resultado['comision_usd']),
                         (Decimal('10'), Decimal('8'), Decimal('2.40')))

    def test_escala_ausente_o_duplicada_no_paga(self):
        venta = [{'unidades': 3, 'base_usd': '5'}]
        for escalas in ([], [{'unidades': 1, 'porcentaje': 5}, {'unidades': 1, 'porcentaje': 6}]):
            with self.subTest(escalas=escalas), self.assertRaises(ValidationError):
                calcular_comision_periodo(venta, escalas)

    def test_rechaza_unidades_y_montos_invalidos(self):
        with self.assertRaises(ValidationError):
            calcular_comision_periodo([{'unidades': '-1', 'base_usd': 10}], [{'unidades': 0, 'porcentaje': 5}])
