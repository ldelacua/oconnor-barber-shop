from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from . import tests as base
from .models import Compra, DetalleCompra, MovimientoInventario
from .services import actualizar_compra

class GuardiasCompraTests(TestCase):
    setUpTestData = classmethod(base.InventarioTests.setUpTestData.__func__)
    compra = base.InventarioTests.compra

    def test_actualizada_no_se_altera_mediante_orm(self):
        compra = self.compra()
        actualizar_compra(compra.pk, 'inventario', 0)
        detalle = compra.detalles.get()
        for consulta, campo in [
            (Compra.objects.filter(pk=compra.pk), {'observacion':'CAMBIO'}),
            (DetalleCompra.objects.filter(pk=detalle.pk), {'cantidad': 4}),
        ]:
            with self.subTest(modelo=consulta.model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                consulta.update(**campo)
            with self.assertRaises(IntegrityError), transaction.atomic():
                consulta.delete()
        with self.assertRaises(ValidationError):
            MovimientoInventario.objects.filter(detalle=detalle).update(cantidad=4)
        compra.refresh_from_db()
        self.assertEqual(compra.observacion, '')
        detalle.refresh_from_db()
        self.assertEqual(detalle.cantidad, 3)

    def test_rechaza_actualizacion_sin_movimientos(self):
        compra = self.compra()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Compra.objects.filter(pk=compra.pk).update(estado='A')
        compra.refresh_from_db()
        self.assertEqual(compra.estado, 'B')

    def test_no_crea_ni_actualiza_una_compra_sin_operacion(self):
        with self.assertRaises(ValidationError):
            Compra.objects.create(proveedor=self.proveedor, numero_factura='INVALIDA',
                tasa_cambio=40, registrada_por='PRUEBA', estado='A')
        compra = self.compra()
        compra.estado = 'A'
        with self.assertRaises(ValidationError):
            compra.save()
        compra.refresh_from_db()
        self.assertEqual(compra.estado, 'B')

    def test_rechaza_movimiento_con_cantidad_incorrecta(self):
        compra = self.compra()
        detalle = compra.detalles.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MovimientoInventario.objects.create(detalle=detalle, cantidad=4, costo_unitario_usd=10)
        self.assertFalse(MovimientoInventario.objects.filter(detalle=detalle).exists())

    def test_no_puede_eludir_actualizacion_con_expresion_sql(self):
        from django.db.models import Value
        compra = self.compra()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Compra.objects.filter(pk=compra.pk).update(estado=Value('A'))
        compra.refresh_from_db()
        self.assertEqual(compra.estado, 'B')
