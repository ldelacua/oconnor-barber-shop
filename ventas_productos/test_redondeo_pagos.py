from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from ventas.pagos_calculos import preparar_pagos
from .models import PagoProducto


class RedondeoPagosTests(SimpleTestCase):
    def preparar(self, monto, total, tasa, moneda='USD'):
        return preparar_pagos([dict(tipo_pago=1, monto=monto, fecha=date(2026,10,26))],
            D(total), D(tasa), {1:dict(id=1,nombre='ZELLE',moneda=moneda)})[0]

    def test_pago_usd_concilia_y_muestra_ajuste_en_factura(self):
        pago=PagoProducto(**self.preparar('35.01','34308.63','980'))
        self.assertEqual(pago.monto,D('35.01'))
        self.assertEqual(pago.equivalente_bs,D('34309.80'))
        self.assertEqual(pago.ajuste_redondeo_bs,D('-1.17'))
        self.assertEqual(pago.equivalente_aplicado_bs,D('34308.63'))
        documento=SimpleNamespace(pagos=SimpleNamespace(all=lambda:[pago]))
        html=render_to_string('ventas_productos/documento.html',dict(documento=documento))
        self.assertIn('34,308.63',html)
        self.assertIn('Incluye ajuste de redondeo: -1.17 Bs',html)
        self.assertNotIn('34,309.80',html)

    def test_ajuste_positivo_y_reverso(self):
        pago=PagoProducto(**self.preparar('35.00','34303.00','980'))
        self.assertEqual(pago.ajuste_redondeo_bs,D('3.00'))
        self.assertEqual(pago.equivalente_aplicado_bs,D('34303.00'))
        reverso=PagoProducto(equivalente_bs=-pago.equivalente_bs,
            ajuste_redondeo_bs=-pago.ajuste_redondeo_bs)
        self.assertEqual(reverso.equivalente_aplicado_bs,-pago.equivalente_aplicado_bs)

    def test_pago_bs_no_tiene_ajuste(self):
        pago=PagoProducto(**self.preparar('34308.63','34308.63','980','BS'))
        self.assertEqual(pago.ajuste_redondeo_bs,D('0'))
        self.assertEqual(pago.equivalente_aplicado_bs,D('34308.63'))

    def test_sigue_rechazando_pago_usd_incorrecto(self):
        with self.assertRaises(ValueError):
            self.preparar('35.02','34308.63','980')
