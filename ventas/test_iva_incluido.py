import uuid
from decimal import Decimal as D
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from tasas_bcv.models import TasaBCV
from ventas.calculos import calcular_linea_iva_incluido
from ventas.models import DocumentoVenta, DetalleVenta
from ventas.servicios import registrar_venta, registrar_reverso
from liquidaciones.servicios import pendientes, registrar


class DesgloseTests(SimpleTestCase):
    def test_formula_inversa_sin_aumentar_cobro(self):
        l=calcular_linea_iva_incluido(D('116'),1,D('40'),D('16'))
        self.assertEqual(l['monto_servicio'],D('116'))
        self.assertEqual(l['base_imponible_usd'],D('100'))
        self.assertEqual(l['base_imponible_bs'],D('4000'))
        self.assertEqual(l['monto_impuesto'],D('640'))
        self.assertEqual(l['base_imponible_bs']+l['monto_impuesto'],D('4640'))

    def test_descuento_antes_desglosar_iva(self):
        l=calcular_linea_iva_incluido(D('116'),2,D('40'),D('16'),D('25'))
        self.assertEqual(l['monto_servicio'],D('232'))
        self.assertEqual(l['monto_descuento_usd'],D('58'))
        self.assertEqual(l['base_imponible_usd'],D('150'))
        self.assertEqual(l['monto_impuesto'],D('960'))
        self.assertEqual(l['base_imponible_bs']+l['monto_impuesto'],D('6960'))

    def test_redondeos_cuadran_cada_linea(self):
        for precio in ['0.01','0.03','0.05','10.11','9999.99']:
            for tasa in ['1.01','10','40.33']:
                for iva in ['0','8','16','16.50','100']:
                    with self.subTest(precio=precio,tasa=tasa,iva=iva):
                        l=calcular_linea_iva_incluido(D(precio),3,D(tasa),D(iva),D('33.33'))
                        self.assertEqual(l['base_imponible_bs']+l['monto_impuesto'],l['monto_servicio_bs']-l['monto_descuento_bs'])
                        self.assertTrue(all(v.as_tuple().exponent == -2 for v in l.values()))


class VentaIvaIncluidoTests(TestCase):
    def setUp(self):
        self.fecha=timezone.localdate()
        self.usuario=get_user_model().objects.create_superuser(username='iva',password='prueba')
        self.client.force_login(self.usuario)
        self.cliente=Cliente.objects.create(nombre='CLIENTE',apellido='IVA',telefono='04121234567')
        self.prestador=Barbero.objects.create(codigo='IVA',nombre='PRESTADOR',apellido='IVA',direccion='A',telefono='1',fecha_ingreso=self.fecha,porcentaje=50)
        self.servicio=Servicio.objects.create(codigo='IVA1',nombre='CORTE',precio=116,duracion=30,retencion_impuesto=True)
        self.manual=Servicio.objects.create(codigo='IVA2',nombre='MANUAL',precio=0,duracion=30,modo_precio='manual',retencion_impuesto=True)
        TasaBCV.objects.create(fecha=self.fecha,tasa_bcv=40)
        self.catalogo={5:{'id':5,'nombre':'Efectivo USD','moneda':'USD'},6:{'id':6,'nombre':'Efectivo Bs.','moneda':'BS'}}
        for ruta,valor in [('ventas.servicios.leer_impuesto',D('16')),('ventas.servicios.leer_tipos_pago',self.catalogo),('liquidaciones.servicios.leer_tipos_pago',self.catalogo)]:
            p=patch(ruta,return_value=valor);p.start();self.addCleanup(p.stop)

    def pago(self,importe,tipo=5):
        return dict(tipo_pago=str(tipo),monto=D(str(importe)),fecha=self.fecha)

    def vender(self,**kwargs):
        datos=dict(fecha=self.fecha,cliente=self.cliente,lineas=[dict(servicio=self.servicio,barbero=self.prestador,cantidad_servicio=1)],
                   pagos=[self.pago('116')],clave=uuid.uuid4(),usuario=self.usuario)
        datos.update(kwargs)
        return registrar_venta(**datos)

    def liquidar(self,doc,monto):
        return registrar(prestador_id=self.prestador.pk,desde=self.fecha,hasta=self.fecha,fecha=self.fecha,
                         seleccion=[doc.detalles.get().pk],pagos=[self.pago(monto)],clave=uuid.uuid4(),usuario=self.usuario)

    def test_guardado_y_liquidacion_sobre_original(self):
        fa=self.vender();l=fa.detalles.get()
        self.assertTrue(fa.iva_incluido)
        self.assertEqual((fa.subtotal_usd,fa.subtotal_bs,fa.total_impuesto_bs,fa.total_bs),(D('100'),D('4000'),D('640'),D('4640')))
        self.assertEqual((l.monto_servicio,l.base_imponible_usd),(D('116'),D('100')))
        self.assertEqual(fa.total_usd,D('116'))
        self.assertEqual(fa.subtotal_bruto_usd,D('116'))
        liq=self.liquidar(fa,'58')
        self.assertEqual(liq.total_servicios_usd,D('116'))
        self.assertEqual(liq.total_comision_usd,D('58'))
        self.assertEqual(liq.detalles.get().monto_servicio_usd,D('116'))

    def test_descuento_no_reduce_comision_y_no_suma_iva(self):
        fa=self.vender(aplicar_descuento=True,descuento_porcentaje=D('25'),pagos=[self.pago('87')])
        l=fa.detalles.get()
        self.assertEqual(fa.descuento_usd,D('29'))
        self.assertEqual(fa.subtotal_usd,D('75'))
        self.assertEqual(fa.total_impuesto_bs,D('480'))
        self.assertEqual(fa.total_bs,D('3480'))
        self.assertEqual(fa.subtotal_bruto_usd,D('116'))
        self.assertEqual(fa.subtotal_bruto_bs,D('4640'))
        self.assertEqual(l.monto_neto_usd,D('87'))
        self.assertEqual(self.liquidar(fa,'58').total_comision_usd,D('58'))

    def test_pagos_mixtos_cubren_original(self):
        fa=self.vender(pagos=[self.pago('100'),self.pago('640',6)])
        self.assertEqual(fa.total_bs,D('4640'))
        self.assertEqual(fa.pagos.count(),2)

    def test_rechaza_cobro_con_impuesto_sumado(self):
        with self.assertRaises(ValidationError):self.vender(pagos=[self.pago('134.56')])
        self.assertFalse(DocumentoVenta.objects.exists())

    def test_manual_y_varios_servicios_suman_bases_por_linea(self):
        fa=self.vender(lineas=[dict(servicio=self.servicio,barbero=self.prestador,cantidad_servicio=2),
                               dict(servicio=self.manual,barbero=self.prestador,cantidad_servicio=3,precio_unitario_usd=D('11.60'))],
                       pagos=[self.pago('266.80')])
        self.assertEqual(fa.subtotal_usd,D('230'))
        self.assertEqual(fa.total_impuesto_bs,D('1472'))
        self.assertEqual(fa.total_bs,D('10672'))
        self.assertEqual(sum(l.monto_servicio for l in fa.detalles.all()),D('266.80'))

    def test_impuesto_cero(self):
        with patch('ventas.servicios.leer_impuesto',return_value=D('0')):fa=self.vender()
        self.assertEqual(fa.subtotal_usd,D('116'))
        self.assertEqual(fa.total_impuesto_bs,D('0'))
        self.assertEqual(fa.total_bs,D('4640'))

    def test_descuento_total_y_reverso_sin_pagos(self):
        fa=self.vender(aplicar_descuento=True,descuento_porcentaje=D('100'),pagos=[])
        l=fa.detalles.get()
        self.assertEqual(l.base_imponible_usd,D('0'))
        self.assertEqual(fa.total_impuesto_bs,D('0'))
        self.assertEqual(fa.total_bs,D('0'))
        self.assertEqual(self.liquidar(fa,'58').total_comision_usd,D('58'))
        re=registrar_reverso(documento_id=fa.pk,motivo='PRUEBA',usuario=self.usuario)
        self.assertFalse(re.pagos.exists())
        self.assertEqual(re.detalles.get().monto_servicio,D('-116'))

    def test_reverso_no_recalcula_configuracion_ni_precio(self):
        fa=self.vender(aplicar_descuento=True,descuento_porcentaje=D('25'),pagos=[self.pago('87')])
        self.liquidar(fa,'58')
        Servicio.objects.filter(pk=self.servicio.pk).update(precio=999)
        Barbero.objects.filter(pk=self.prestador.pk).update(porcentaje=10)
        with patch('ventas.servicios.leer_impuesto',return_value=D('25')):
            re=registrar_reverso(documento_id=fa.pk,motivo='PRUEBA',usuario=self.usuario)
        self.assertTrue(re.iva_incluido)
        for campo in ['monto_servicio','base_imponible_usd','base_imponible_bs','monto_impuesto','monto_descuento_usd']:
            self.assertEqual(getattr(re.detalles.get(),campo),-getattr(fa.detalles.get(),campo))
        _,ajustes=pendientes(self.prestador,self.fecha,self.fecha,self.fecha)
        self.assertEqual(ajustes[0]['comision'],D('-58'))
        self.assertEqual(ajustes[0]['base'],D('-116'))
        self.assertEqual(re.total_bs,-fa.total_bs)

    def test_sql_bloquea_cambiar_modo_y_bases_de_documento_sellado(self):
        fa=self.vender()
        for sql,params in [('UPDATE ventas_documentoventa SET iva_incluido=0 WHERE id_documento=%s',[fa.pk]),
                           ('UPDATE ventas_detalleventa SET base_imponible_usd=1 WHERE id_documento=%s',[fa.pk]),
                           ('DELETE FROM ventas_detalleventa WHERE id_documento=%s',[fa.pk])]:
            with self.subTest(sql=sql),self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as c:c.execute(sql,params)

    def test_sql_bloquea_base_imponible_inventada(self):
        doc=DocumentoVenta.objects.create(tipo_documento='FA',fecha=self.fecha,cliente=self.cliente,iva_incluido=True,
                tasa_bcv=40,impuesto=16,subtotal_usd=1,subtotal_bs=40,total_impuesto_bs=4600,total_bs=4640,registrado_por='iva')
        with self.assertRaises(IntegrityError),transaction.atomic():
            DetalleVenta.objects.create(documento=doc,servicio=self.servicio,barbero=self.prestador,descripcion_barbero='PRESTADOR IVA',
                codigo_servicio='IVA1',descripcion_servicio='CORTE',cantidad_servicio=1,precio_unitario_usd=116,monto_servicio=116,
                monto_servicio_bs=4640,monto_impuesto=4600,base_imponible_usd=1,base_imponible_bs=40)

    def test_factura_explicita_desglose_y_monto_cobrado(self):
        fa=self.vender()
        r=self.client.get(reverse('ventas:ver',args=[fa.pk]))
        self.assertContains(r,'Base imponible USD')
        self.assertContains(r,'IVA aplicado (16%) Bs.')
        self.assertContains(r,'El desglose inverso no aumenta el precio')
        self.assertContains(r,'116.00')
        self.assertNotContains(r,'134.56')
