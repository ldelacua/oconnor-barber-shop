from datetime import date
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from . import tests as base
from .models import CierreMensual, DetalleCierre

class GuardiasCierreTests(TestCase):
    setUpTestData = classmethod(base.ControlInventarioTests.setUpTestData.__func__)
    iniciar = base.ControlInventarioTests.iniciar
    contar = base.ControlInventarioTests.contar
    cerrar = base.ControlInventarioTests.cerrar

    def test_teorico_abierto_no_se_altera_mediante_orm(self):
        cierre = self.iniciar()
        detalle = cierre.detalles.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleCierre.objects.filter(pk=detalle.pk).update(teorico=100)
        detalle.teorico = 100
        with self.assertRaises(ValidationError):
            detalle.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(periodo=date(2026,11,1))

    def test_cierre_finalizado_no_se_altera_mediante_orm(self):
        cierre = self.cerrar(30, 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(observacion='CAMBIO')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleCierre.objects.filter(cierre=cierre).update(fisico=1)
        detalle = cierre.detalles.first()
        detalle.fisico = 1
        with self.assertRaises(ValidationError):
            detalle.save()
        with self.assertRaises(ValidationError):
            cierre.delete()

    def test_no_finaliza_cierre_sin_contar_todos_los_productos(self):
        from django.utils import timezone
        cierre = self.iniciar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(
                estado='C', cerrado_por='PRUEBA', cerrado_en=timezone.now())
        cierre.refresh_from_db()
        self.assertEqual(cierre.estado, 'B')

    def test_no_sella_ajuste_sin_productos(self):
        from .models import DocumentoAjuste
        doc = DocumentoAjuste.objects.create(tipo='EN', fecha=date(2026,10,10),
            observacion='PRUEBA', registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoAjuste.objects.filter(pk=doc.pk).update(sellado=True)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)

    def test_no_sella_salida_con_stock_insuficiente(self):
        from .models import DocumentoAjuste, DetalleAjuste
        doc = DocumentoAjuste.objects.create(tipo='SA', fecha=date(2026,10,10),
            observacion='PRUEBA', registrado_por='PRUEBA')
        DetalleAjuste.objects.create(documento=doc, producto=self.producto,
            descripcion='PRUEBA', cantidad=31, costo_unitario_usd=3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoAjuste.objects.filter(pk=doc.pk).update(sellado=True)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)

    def test_no_cierra_sin_ajustar_la_diferencia_fisica(self):
        from django.utils import timezone
        cierre = self.iniciar()
        self.contar(cierre, 25, 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CierreMensual.objects.filter(pk=cierre.pk).update(
                estado='C', cerrado_por='PRUEBA', cerrado_en=timezone.now())
        cierre.refresh_from_db()
        self.assertEqual(cierre.estado, 'B')

    def test_no_inicia_cierre_en_un_dia_distinto_al_primero(self):
        with self.assertRaises(ValidationError):
            CierreMensual.objects.create(periodo=date(2026, 10, 15), iniciado_por='PRUEBA')

    def test_no_puede_eludir_sellado_del_ajuste_con_valor_numerico(self):
        from .models import DocumentoAjuste
        doc = DocumentoAjuste.objects.create(tipo='EN', fecha=date(2026,10,10),
            observacion='PRUEBA', registrado_por='PRUEBA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoAjuste.objects.filter(pk=doc.pk).update(sellado=1)
        doc.refresh_from_db()
        self.assertFalse(doc.sellado)
