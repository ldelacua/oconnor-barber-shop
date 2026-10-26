import uuid
from decimal import Decimal as D
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.urls import reverse
from servicios.models import Servicio
from servicios.forms import ServicioForm
from ventas.models import DocumentoVenta, DetalleVenta
from ventas.servicios import registrar_reverso
from ventas import test_iva_incluido as base


class RetencionTests(TestCase):
    setUp = base.VentaIvaIncluidoTests.setUp
    pago = base.VentaIvaIncluidoTests.pago
    vender = base.VentaIvaIncluidoTests.vender
    liquidar = base.VentaIvaIncluidoTests.liquidar

    def test_desmarcado_calcula_iva_normal_y_comision_original(self):
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=False)
        fa=self.vender(pagos=[self.pago("134.56")]);l=fa.detalles.get()
        self.assertFalse(l.retencion_impuesto)
        self.assertEqual((l.base_imponible_usd,l.monto_impuesto,fa.total_bs),(D('116'),D('742.40'),D('5382.40')))
        self.assertEqual(self.liquidar(fa,'58').total_comision_usd,D('58'))

    def test_factura_mixta_cada_linea_con_su_tratamiento(self):
        otro=Servicio.objects.create(codigo='SINIVA',nombre='SIN IVA',precio=116,duracion=30)
        fa=self.vender(lineas=[dict(servicio=self.servicio,barbero=self.prestador,cantidad_servicio=1),
                               dict(servicio=otro,barbero=self.prestador,cantidad_servicio=1)],pagos=[self.pago('250.56')])
        self.assertEqual((fa.subtotal_usd,fa.total_impuesto_bs,fa.total_bs),(D('216'),D('1382.40'),D('10022.40')))
        self.assertEqual(list(fa.detalles.values_list('retencion_impuesto',flat=True)),[True,False])
        r=self.client.get(reverse('ventas:ver',args=[fa.pk]))
        self.assertContains(r,'IVA adicional · 16%');self.assertContains(r,'IVA incluido · 16%')

    def test_descuento_mixto_aplica_iva_solo_al_marcado(self):
        otro=Servicio.objects.create(codigo='SINIVA',nombre='SIN IVA',precio=116,duracion=30)
        fa=self.vender(lineas=[dict(servicio=self.servicio,barbero=self.prestador,cantidad_servicio=1),
                               dict(servicio=otro,barbero=self.prestador,cantidad_servicio=1)],pagos=[self.pago('187.92')],
                       aplicar_descuento=True,descuento_porcentaje=D('25'))
        self.assertEqual((fa.subtotal_usd,fa.total_impuesto_bs,fa.total_bs),(D('162'),D('1036.80'),D('7516.80')))
        self.assertEqual(sum(l.monto_servicio for l in fa.detalles.all()),D('232'))

    def test_reverso_copia_opcion_historica_aunque_se_cambie_servicio(self):
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=False)
        fa=self.vender(pagos=[self.pago("134.56")])
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=True)
        re=registrar_reverso(documento_id=fa.pk,motivo='PRUEBA',usuario=self.usuario)
        self.assertFalse(re.detalles.get().retencion_impuesto)
        self.assertEqual(re.total_impuesto_bs,D("-742.40"))
        self.assertTrue(re.detalles.get().impuesto_normal)
        self.assertEqual(re.total_bs,-fa.total_bs)

    def test_sql_rechaza_opcion_distinta_al_maestro(self):
        doc=DocumentoVenta.objects.create(tipo_documento='FA',fecha=self.fecha,cliente=self.cliente,iva_incluido=True,
                tasa_bcv=40,impuesto=16,subtotal_usd=116,subtotal_bs=4640,total_impuesto_bs=0,total_bs=4640,registrado_por='iva')
        with self.assertRaises(IntegrityError),transaction.atomic():
            DetalleVenta.objects.create(documento=doc,servicio=self.servicio,barbero=self.prestador,descripcion_barbero='PRESTADOR IVA',
                codigo_servicio='IVA1',descripcion_servicio='CORTE',cantidad_servicio=1,precio_unitario_usd=116,monto_servicio=116,
                monto_servicio_bs=4640,monto_impuesto=0,base_imponible_usd=116,base_imponible_bs=4640,retencion_impuesto=False)

    def test_formulario_guarda_booleano_y_nuevo_sin_marcar(self):
        self.assertFalse(Servicio().retencion_impuesto)
        datos=dict(codigo='NUEVO',nombre='NUEVO',precio='116',duracion=30,modo_precio='automatico',activo='on',retencion_impuesto='on')
        f=ServicioForm(datos);self.assertTrue(f.is_valid(),f.errors);s=f.save();self.assertTrue(s.retencion_impuesto)
        datos.pop('retencion_impuesto');f=ServicioForm(datos,instance=s);self.assertTrue(f.is_valid(),f.errors);self.assertFalse(f.save().retencion_impuesto)
        r=self.client.get(reverse('servicios:editar',args=[s.pk]));self.assertContains(r,'Retención de impuesto')

    def test_formulario_venta_envia_opciones_fiscales_reales(self):
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=False)
        r=self.client.get(reverse('ventas:crear'))
        self.assertContains(r,'retenciones-servicios')
        self.assertContains(r,'"'+str(self.servicio.pk)+'": false')

    def test_normal_redondeo_descuento_y_original_bs(self):
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=False)
        fa=self.vender(aplicar_descuento=True,descuento_porcentaje=D('25'),pagos=[self.pago('100.92')])
        self.assertEqual(fa.subtotal_usd,D('87'))
        self.assertEqual(fa.total_impuesto_bs,D('556.80'))
        self.assertEqual(fa.total_bs,D('4036.80'))
        self.assertEqual(fa.subtotal_bruto_bs,D('4640'))
        self.assertEqual(self.liquidar(fa,'58').total_comision_usd,D('58'))

    def test_normal_descuento_total_cero_y_reverso(self):
        Servicio.objects.filter(pk=self.servicio.pk).update(retencion_impuesto=False)
        fa=self.vender(aplicar_descuento=True,descuento_porcentaje=D('100'),pagos=[])
        self.assertEqual(fa.total_bs,0)
        self.assertTrue(fa.detalles.get().impuesto_normal)
        re=registrar_reverso(documento_id=fa.pk,motivo='PRUEBA',usuario=self.usuario)
        self.assertTrue(re.detalles.get().impuesto_normal)
        self.assertEqual(re.total_bs,0)
