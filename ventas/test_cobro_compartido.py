from datetime import date
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .cobro_compartido import distribuir_pago_unico


class CobroCompartidoTests(SimpleTestCase):
    catalogo = {
        1: {"id": 1, "nombre": "Transferencia", "moneda": "BS"},
        2: {"id": 2, "nombre": "Efectivo USD", "moneda": "USD"},
    }

    def test_distribuye_una_transferencia_sin_duplicar_cuenta(self):
        pago = {"tipo_pago": 1, "monto": D("10000"), "fecha": date(2026, 11, 8),
                "cuenta_bancaria": object(), "referencia": "123"}
        servicios, productos = distribuir_pago_unico(pago, D("8000"), D("2000"), D("1000"), self.catalogo)
        self.assertEqual((servicios[0]["monto"], productos[0]["monto"]), (D("8000"), D("2000")))
        self.assertIsNone(servicios[0]["cuenta_bancaria"])
        self.assertIsNone(productos[0]["cuenta_bancaria"])
        self.assertIsNotNone(pago["cuenta_bancaria"])

    def test_no_inventa_un_centavo_al_repartir_dolares(self):
        pago = {"tipo_pago": 2, "monto": D("1.01"), "fecha": date(2026, 11, 8)}
        with self.assertRaisesMessage(ValidationError, "redondeo"):
            distribuir_pago_unico(pago, D("100.40"), D("0.40"), D("100"), self.catalogo)
