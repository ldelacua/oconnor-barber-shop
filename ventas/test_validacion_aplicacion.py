from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from . import test_iva_incluido as base
from .servicios import _sellar
from .models import DocumentoVenta

class ValidacionAplicacionTests(TestCase):
    setUp = base.VentaIvaIncluidoTests.setUp
    vender = base.VentaIvaIncluidoTests.vender
    pago = base.VentaIvaIncluidoTests.pago
    def test_rechaza_factura_inconsistente_antes_del_sellado(self):
        def alterar_total(documento):
            documento.total_bs += Decimal('1.00')
            _sellar(documento)
        with patch('ventas.servicios._sellar', side_effect=alterar_total):
            with self.assertRaises(ValidationError):
                self.vender()
        self.assertFalse(DocumentoVenta.objects.exists())

    def test_rechaza_impuesto_de_detalle_alterado(self):
        from copy import copy
        from types import SimpleNamespace
        from .servicios import _validar_sello
        factura = self.vender()
        linea = copy(factura.detalles.get())
        linea.monto_impuesto += Decimal('1.00')
        datos = dict(factura.__dict__)
        datos.update(detalles=SimpleNamespace(all=lambda:[linea]),
                     pagos=SimpleNamespace(all=lambda:list(factura.pagos.all())))
        with self.assertRaises(ValidationError):
            _validar_sello(SimpleNamespace(**datos))

    def test_rechaza_cantidad_alterada_en_reverso(self):
        from copy import copy
        from types import SimpleNamespace
        from .servicios import _validar_sello, registrar_reverso
        factura = self.vender()
        reverso = registrar_reverso(documento_id=factura.pk, motivo='PRUEBA', usuario=self.usuario)
        linea = copy(reverso.detalles.get())
        linea.cantidad_servicio += 1
        datos = dict(reverso.__dict__)
        datos.update(detalles=SimpleNamespace(all=lambda:[linea]),
                     pagos=SimpleNamespace(all=lambda:list(reverso.pagos.all())),
                     documento_original=factura)
        with self.assertRaises(ValidationError):
            _validar_sello(SimpleNamespace(**datos))

    def test_no_crea_factura_ya_finalizada(self):
        with self.assertRaises(ValidationError):
            DocumentoVenta.objects.create(tipo_documento='FA', fecha=self.fecha,
                cliente=self.cliente, tasa_bcv=40, impuesto=16, subtotal_usd=0,
                subtotal_bs=0, total_impuesto_bs=0, total_bs=0,
                registrado_por='PRUEBA', sellado=True)

    def test_rechaza_equivalente_incorrecto_en_pago_de_factura(self):
        from django.db import IntegrityError, transaction
        from .models import PagoVenta
        factura = DocumentoVenta.objects.create(tipo_documento='FA', fecha=self.fecha,
            cliente=self.cliente, tasa_bcv=40, impuesto=16, subtotal_usd=1,
            subtotal_bs=40, total_impuesto_bs=0, total_bs=40, registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PagoVenta.objects.create(documento=factura, tipo_pago=5, nombre_tipo_pago='USD',
                moneda='USD', fecha=self.fecha, monto=10, equivalente_bs=1)

    def test_rechaza_comision_incorrecta_en_liquidacion(self):
        from django.db import IntegrityError, transaction
        from liquidaciones.models import Liquidacion, DetalleLiquidacion
        factura = self.vender()
        liquidacion = Liquidacion.objects.create(prestador=self.prestador, nombre_prestador='PRUEBA',
            periodo_desde=self.fecha, periodo_hasta=self.fecha, fecha_cancelacion=self.fecha,
            tasa_bcv=40, total_servicios_usd=116, total_comision_usd=58,
            total_bs=2320, registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleLiquidacion.objects.create(liquidacion=liquidacion,
                detalle_venta=factura.detalles.get(), porcentaje=50,
                monto_servicio_usd=116, comision_usd=1)

    def test_rechaza_equivalente_incorrecto_en_pago_de_liquidacion(self):
        from django.db import IntegrityError, transaction
        from liquidaciones.models import Liquidacion, PagoLiquidacion
        liquidacion = Liquidacion.objects.create(prestador=self.prestador, nombre_prestador='PRUEBA',
            periodo_desde=self.fecha, periodo_hasta=self.fecha, fecha_cancelacion=self.fecha,
            tasa_bcv=40, total_servicios_usd=116, total_comision_usd=58,
            total_bs=2320, registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PagoLiquidacion.objects.create(liquidacion=liquidacion, tipo_pago=5, nombre_tipo_pago='USD',
                moneda='USD', fecha=self.fecha, monto=10, equivalente_bs=1)

    def test_rechaza_cabecera_de_reverso_alterada(self):
        from django.db import IntegrityError, transaction
        original = self.vender()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoVenta.objects.create(tipo_documento='RE', fecha=self.fecha,
                cliente=self.cliente, tasa_bcv=original.tasa_bcv, impuesto=original.impuesto,
                iva_incluido=original.iva_incluido, documento_original=original,
                subtotal_usd=-original.subtotal_usd, subtotal_bs=-original.subtotal_bs,
                total_impuesto_bs=-original.total_impuesto_bs, total_bs=-1,
                descuento_porcentaje=original.descuento_porcentaje,
                descuento_usd=-original.descuento_usd, descuento_bs=-original.descuento_bs,
                registrado_por='PRUEBA')

    def test_rechaza_periodo_invalido_de_liquidacion(self):
        from datetime import timedelta
        from liquidaciones.models import Liquidacion
        with self.assertRaises(ValidationError):
            Liquidacion.objects.create(prestador=self.prestador, nombre_prestador='PRUEBA',
                periodo_desde=self.fecha, periodo_hasta=self.fecha + timedelta(days=1),
                fecha_cancelacion=self.fecha, tasa_bcv=40, total_servicios_usd=116,
                total_comision_usd=58, total_bs=2320, registrado_por='PRUEBA')
