from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.db import IntegrityError
from . import tests as base
from .models import DocumentoProducto, LineaProducto, PagoProducto
from .servicios import sellar
from inventario.existencias import existencia_producto

class ValidacionAplicacionTests(TestCase):
    setUpTestData = classmethod(base.VentaProductosTests.setUpTestData.__func__)
    venta = base.VentaProductosTests.venta

    def test_rechaza_total_alterado_y_revierte_stock(self):
        def alterar_total(doc):
            DocumentoProducto.objects.filter(pk=doc.pk).update(total_bs=Decimal('1.00'))
            sellar(doc)
        with patch('ventas_productos.servicios.sellar', side_effect=alterar_total):
            with self.assertRaises(ValidationError):
                self.venta()
        self.assertFalse(DocumentoProducto.objects.exists())
        self.assertEqual(existencia_producto(self.producto.pk),Decimal('5.00'))

    def test_documentos_guardados_no_admiten_modificacion_por_orm(self):
        documento = self.venta()
        for consulta in [DocumentoProducto.objects.filter(pk=documento.pk),
                         LineaProducto.objects.filter(documento=documento),
                         PagoProducto.objects.filter(documento=documento)]:
            with self.subTest(modelo=consulta.model.__name__):
                with self.assertRaises(ValidationError):
                    consulta.update(documento_id=documento.pk) if consulta.model is not DocumentoProducto else consulta.update(observacion="ALTERADA")
                with self.assertRaises(ValidationError):
                    consulta.delete()
        self.assertEqual(DocumentoProducto.objects.get(pk=documento.pk).observacion, "COMPRA CLIENTE")

    def test_no_puede_sellar_venta_sin_detalles_desde_orm(self):
        from datetime import date
        doc = DocumentoProducto.objects.create(tipo='VP', fecha=date(2026,10,20),
            cliente=self.cliente, descripcion_cliente='', tasa_bcv=40, iva=16,
            subtotal_usd=0, subtotal_bs=0, impuesto_bs=0, total_bs=0, registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError):
            DocumentoProducto.objects.filter(pk=doc.pk).update(sellado=True)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)

    def test_no_crea_un_documento_ya_finalizado(self):
        from datetime import date
        with self.assertRaises(ValidationError):
            DocumentoProducto.objects.create(tipo='VP', fecha=date(2026,10,20),
                cliente=self.cliente, descripcion_cliente='', tasa_bcv=40, iva=16,
                subtotal_usd=0, subtotal_bs=0, impuesto_bs=0, total_bs=0,
                registrado_por='PRUEBA', sellado=True)

    def test_rechaza_descuento_negativo_incluso_si_los_totales_cuadran(self):
        from datetime import date
        from django.db import transaction
        doc = DocumentoProducto.objects.create(tipo='VP', fecha=date(2026,10,20),
            cliente=self.cliente, descripcion_cliente='PRUEBA', tasa_bcv=40, iva=16,
            subtotal_usd=10, subtotal_bs=400, impuesto_bs=Decimal('70.40'), total_bs=Decimal('510.40'),
            descuento_porcentaje=-10, descuento_usd=-1, descuento_bs=-40, unidades_total=1,
            precio_automatico=True, registrado_por='PRUEBA')
        LineaProducto.objects.create(documento=doc, producto=self.producto, descripcion='PRUEBA',
            codigo='VP-1', cantidad=1, precio_unitario_usd=10, subtotal_usd=10, subtotal_bs=400,
            impuesto_bs=Decimal('70.40'), costo_unitario_usd=4, porcentaje_venta=150,
            descuento_usd=-1, descuento_bs=-40)
        PagoProducto.objects.create(documento=doc, tipo_pago=5, nombre_tipo_pago='USD',
            moneda='USD', fecha=date(2026,10,20), monto=Decimal('12.76'), equivalente_bs=Decimal('510.40'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoProducto.objects.filter(pk=doc.pk).update(sellado=True)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)

    def test_no_puede_eludir_el_sellado_con_valor_numerico(self):
        from datetime import date
        from django.db import transaction
        doc = DocumentoProducto.objects.create(tipo='VP', fecha=date(2026,10,20),
            cliente=self.cliente, descripcion_cliente='', tasa_bcv=40, iva=16,
            subtotal_usd=0, subtotal_bs=0, impuesto_bs=0, total_bs=0, registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoProducto.objects.filter(pk=doc.pk).update(sellado=1)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)
