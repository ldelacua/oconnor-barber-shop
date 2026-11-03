from decimal import Decimal as D
from types import SimpleNamespace
from django.test import SimpleTestCase
from .pagos_calculos import validar_pagos_guardados

class PagosGuardadosTests(SimpleTestCase):
    def pago(self, moneda, monto, equivalente, ajuste=0):
        return SimpleNamespace(moneda=moneda, monto=D(str(monto)),
                               equivalente_bs=D(str(equivalente)), ajuste_redondeo_bs=D(str(ajuste)))

    def test_ajuste_de_cambio_legitimo(self):
        validar_pagos_guardados([self.pago('USD','35.01','34309.80','-1.17')], D('34308.63'), D('980'))

    def test_rechaza_ajuste_inventado_que_oculta_faltante(self):
        with self.assertRaises(ValueError):
            validar_pagos_guardados([self.pago('USD','35.00','34300.00','8.63')], D('34308.63'), D('980'))

    def test_pago_mixto_valido_y_ajuste_en_bolivares_invalido(self):
        validar_pagos_guardados([self.pago('USD',1,40), self.pago('BS',60,60)], D('100'), D('40'))
        with self.assertRaises(ValueError):
            validar_pagos_guardados([self.pago('USD',1,40), self.pago('BS',59,59,1)], D('100'), D('40'))

    def test_cero_admite_solo_ausencia_de_pagos(self):
        validar_pagos_guardados([], D('0'), D('40'))
        with self.assertRaises(ValueError):
            validar_pagos_guardados([self.pago('USD',1,40,-40)], D('0'), D('40'))

    def test_rechaza_ajustes_compensados_en_dos_pagos(self):
        pagos = [self.pago('USD', 1, 40, 5), self.pago('USD', 1, 40, -5)]
        with self.assertRaises(ValueError):
            validar_pagos_guardados(pagos, D('80'), D('40'))
