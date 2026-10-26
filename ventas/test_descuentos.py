import uuid
from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from clientes.models import Cliente
from barberos.models import Barbero
from servicios.models import Servicio
from servicios.forms import ServicioForm
from tasas_bcv.models import TasaBCV
from ventas.models import DocumentoVenta, DetalleVenta, PagoVenta
from ventas.forms import VentaForm, LineaForm
from ventas.servicios import registrar_venta, registrar_reverso
from liquidaciones.servicios import pendientes, registrar
from liquidaciones.models import Liquidacion

D=Decimal

class DescuentosTests(TestCase):
    def setUp(self):
        catalogo={5:{"id":5,"nombre":"Efectivo USD","moneda":"USD"},6:{"id":6,"nombre":"Efectivo Bs.","moneda":"BS"}}
        for ruta,valor in [("ventas.servicios.leer_impuesto",D("16.00")),("ventas.views.leer_impuesto",D("16.00")),
                           ("ventas.servicios.leer_tipos_pago",catalogo),("ventas.views.leer_tipos_pago",catalogo),
                           ("liquidaciones.servicios.leer_tipos_pago",catalogo)]:
            parche=patch(ruta,return_value=valor);parche.start();self.addCleanup(parche.stop)
        self.hoy=timezone.localdate()
        self.user=get_user_model().objects.create_superuser(username='prueba',password='prueba')
        self.client.force_login(self.user)
        self.cliente=Cliente.objects.create(nombre='Cliente',apellido='Prueba',telefono='123')
        self.prestador=Barbero.objects.create(codigo='PS1',nombre='Ana',apellido='Pérez',direccion='a',telefono='1',fecha_ingreso=self.hoy,porcentaje=50)
        self.servicio=Servicio.objects.create(codigo='S1',nombre='Corte',precio=40,duracion=30,retencion_impuesto=True)
        self.manual=Servicio.objects.create(codigo='S2',nombre='Tratamiento',precio=0,duracion=30,modo_precio='manual',retencion_impuesto=True)
        TasaBCV.objects.create(fecha=self.hoy,tasa_bcv=10)

    def pago(self, monto, tipo=5):
        return {'tipo_pago':str(tipo),'fecha':self.hoy,'referencia':'','observacion':'','monto':D(str(monto))}

    def vender(self, descuento=False, porcentaje=50, monto='40.00', servicio=None, precio=None, cantidad=1, pagos=None, clave=None):
        linea={'servicio':servicio or self.servicio,'barbero':self.prestador,'cantidad_servicio':cantidad}
        if precio is not None:linea['precio_unitario_usd']=precio
        return registrar_venta(fecha=self.hoy,cliente=self.cliente,lineas=[linea],
            pagos=pagos if pagos is not None else [self.pago(monto)],clave=clave or uuid.uuid4(),usuario=self.user,
            aplicar_descuento=descuento,descuento_porcentaje=porcentaje)

    def liquidar(self, seleccion, monto):
        return registrar(prestador_id=self.prestador.pk,desde=self.hoy,hasta=self.hoy,fecha=self.hoy,
            seleccion=seleccion,pagos=[self.pago(monto)],clave=uuid.uuid4(),usuario=self.user)

    def test_automatico_ignora_precio_enviado(self):
        doc=self.vender(precio='0.01')
        linea=doc.detalles.get()
        self.assertEqual(linea.precio_unitario_usd,D('40.00'))
        self.assertFalse(linea.precio_manual)
        self.assertEqual(doc.total_bs,D('400.00'))

    def test_manual_toma_precio_del_usuario(self):
        doc=self.vender(servicio=self.manual,precio='55.50',monto='55.50')
        linea=doc.detalles.get()
        self.assertTrue(linea.precio_manual)
        self.assertEqual(linea.monto_servicio,D('55.50'))
        self.assertEqual(doc.total_bs,D('555.00'))

    def test_manual_obligatorio_positivo_y_dos_decimales(self):
        for valor in [None,'0','-1','1.001','NaN','Infinity']:
            with self.subTest(valor=valor),self.assertRaises(ValidationError):self.vender(servicio=self.manual,precio=valor)
        self.assertFalse(DocumentoVenta.objects.exists())

    def test_descuento_impuesto_neto_y_base_integra(self):
        doc=self.vender(descuento=True,monto='20.00')
        linea=doc.detalles.get()
        self.assertEqual(doc.descuento_porcentaje,D('50.00'))
        self.assertEqual(doc.descuento_usd,D('20.00'))
        self.assertEqual(doc.descuento_bs,D('200.00'))
        self.assertEqual(doc.subtotal_usd,D('17.24'))
        self.assertEqual(doc.subtotal_bs,D('172.41'))
        self.assertEqual(doc.total_impuesto_bs,D('27.59'))
        self.assertEqual(doc.total_bs,D('200.00'))
        self.assertEqual(linea.monto_servicio,D('40.00'))
        self.assertEqual(linea.monto_servicio_bs,D('400.00'))
        self.assertEqual(linea.monto_neto_usd,D('20.00'))
        self.assertEqual(doc.subtotal_bruto_usd,D('40.00'))
        candidatas,_=pendientes(self.prestador,self.hoy,self.hoy,self.hoy)
        self.assertEqual(candidatas[0]['comision'],D('20.00'))

    def test_liquidacion_paga_comision_completa_con_descuento(self):
        doc=self.vender(descuento=True,monto='20.00')
        liq=self.liquidar([doc.detalles.get().pk],'20.00')
        self.assertEqual(liq.total_servicios_usd,D('40.00'))
        self.assertEqual(liq.total_comision_usd,D('20.00'))
        self.assertTrue(liq.sellado)

    def test_pago_exacto_de_total_descuento_y_mixto(self):
        doc=self.vender(descuento=True,pagos=[self.pago('10'),self.pago('100',6)])
        self.assertEqual(doc.pagos.count(),2)
        self.assertEqual(doc.total_bs,D('200.00'))

    def test_pago_sobre_importe_sin_descuento_se_rechaza(self):
        with self.assertRaises(ValidationError):self.vender(descuento=True,monto='40.00')
        self.assertFalse(DocumentoVenta.objects.exists())

    def test_descuento_manual_multiplica_cantidad(self):
        doc=self.vender(descuento=True,servicio=self.manual,precio='10.25',cantidad=2,monto='10.25')
        linea=doc.detalles.get()
        self.assertEqual(linea.monto_servicio,D('20.50'))
        self.assertEqual(linea.monto_descuento_usd,D('10.25'))
        self.assertEqual(doc.total_impuesto_bs,D('14.14'))

    def test_porcentaje_otro_y_desactivado_no_descuenta(self):
        doc=self.vender(descuento=True,porcentaje=25,monto='30.00')
        self.assertEqual(doc.subtotal_usd,D('25.86'))
        doc=self.vender(descuento=False,porcentaje=90)
        self.assertEqual(doc.descuento_porcentaje,D('0.00'))
        self.assertEqual(doc.descuento_usd,D('0.00'))

    def test_descuento_invalido(self):
        for p in [-1,0,101,'1.001','NaN','Infinity']:
            with self.subTest(p=p),self.assertRaises(ValidationError):self.vender(descuento=True,porcentaje=p)
        self.assertFalse(DocumentoVenta.objects.exists())

    def test_descuento_total_no_inventa_pagos(self):
        doc=self.vender(descuento=True,porcentaje=100,pagos=[])
        self.assertEqual(doc.total_bs,D('0.00'))
        self.assertFalse(doc.pagos.exists())
        self.assertEqual(doc.detalles.get().monto_servicio,D('40.00'))
        with self.assertRaises(ValidationError):self.vender(descuento=True,porcentaje=100,monto='1')

    def test_reverso_copia_descuento_y_precio_manual_historicos(self):
        fa=self.vender(descuento=True,servicio=self.manual,precio='40',monto='20.00')
        Servicio.objects.filter(pk=self.manual.pk).update(precio=999,modo_precio='automatico')
        with patch('ventas.servicios.leer_impuesto',return_value=D('25')):
            re=registrar_reverso(documento_id=fa.pk,motivo='Error',usuario=self.user)
        self.assertEqual(re.descuento_porcentaje,D('50.00'))
        for campo in ['subtotal_usd','subtotal_bs','descuento_usd','descuento_bs','total_bs','total_impuesto_bs']:
            self.assertEqual(getattr(re,campo),-getattr(fa,campo))
        a=fa.detalles.get();b=re.detalles.get()
        self.assertEqual(b.linea_original_id,a.pk)
        self.assertTrue(b.precio_manual)
        self.assertEqual(b.monto_servicio,-a.monto_servicio)
        self.assertEqual(b.monto_descuento_usd,-a.monto_descuento_usd)
        self.assertEqual(re.pagos.get().monto,D('-20.00'))
        self.assertEqual(re.impuesto,D('16.00'))

    def test_reverso_antes_liquidar_excluye_servicio(self):
        fa=self.vender(descuento=True,monto='20.00')
        registrar_reverso(documento_id=fa.pk,motivo='Error',usuario=self.user)
        self.assertEqual(pendientes(self.prestador,self.hoy,self.hoy,self.hoy),([],[]))

    def test_reverso_despues_liquidar_descontara_comision_completa(self):
        fa=self.vender(descuento=True,monto='20.00')
        self.liquidar([fa.detalles.get().pk],'20')
        registrar_reverso(documento_id=fa.pk,motivo='Error',usuario=self.user)
        nuevo=self.vender(servicio=self.manual,precio='60',monto='60.00')
        servicios,ajustes=pendientes(self.prestador,self.hoy,self.hoy,self.hoy)
        self.assertEqual(ajustes[0]['comision'],D('-20.00'))
        liq=self.liquidar([nuevo.detalles.get().pk],'10')
        self.assertEqual(liq.total_comision_usd,D('10.00'))
        self.assertEqual(Liquidacion.objects.count(),2)

    def test_factura_y_pago_guardados_siguen_inmutables(self):
        fa=self.vender(descuento=True,monto='20.00')
        for sql in ['UPDATE ventas_documentoventa SET descuento_usd=0 WHERE id_documento=%s',
                    'UPDATE ventas_detalleventa SET monto_descuento_usd=0 WHERE id_documento=%s',
                    'DELETE FROM ventas_pagoventa WHERE documento_id=%s']:
            with self.subTest(sql=sql),self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as c:c.execute(sql,[fa.pk])

    def test_idempotencia_no_duplica_documentos(self):
        clave=uuid.uuid4();fa=self.vender(descuento=True,monto='20.00',clave=clave)
        repetida=self.vender(descuento=True,monto='20.00',clave=clave)
        self.assertEqual(fa.pk,repetida.pk);self.assertEqual(DocumentoVenta.objects.count(),1)

    def test_formularios_manual_y_porcentaje(self):
        linea={'servicio':self.manual.pk,'barbero':self.prestador.pk,'cantidad_servicio':1}
        self.assertFalse(LineaForm(linea).is_valid())
        self.assertTrue(LineaForm({**linea,'precio_unitario_usd':'23.25'}).is_valid())
        datos={'fecha':self.hoy,'cliente':self.cliente.pk,'clave':uuid.uuid4(),'aplicar_descuento':'on','descuento_porcentaje':'50'}
        f=VentaForm(datos);self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.cleaned_data['descuento_porcentaje'],D('50'))
        datos.pop('aplicar_descuento');f=VentaForm(datos);self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.cleaned_data['descuento_porcentaje'],D('0'))

    def test_catalogo_servicio_manual_admite_precio_vacio(self):
        f=ServicioForm({'codigo':'OTRO','nombre':'Otro','descripcion':'','modo_precio':'manual','precio':'','duracion':30,'activo':'on'})
        self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.save().precio,0)

    def test_pantallas_se_renderizan(self):
        fa=self.vender(descuento=True,monto='20.00')
        for url in [reverse('ventas:crear'),reverse('ventas:ver',args=[fa.pk]),reverse('servicios:crear'),reverse('servicios:lista')]:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
        r=self.client.get(reverse('ventas:ver',args=[fa.pk]));self.assertContains(r,'Descuento (50%)')

    def test_proteccion_sql_rechaza_precio_automatico_alterado(self):
        doc=DocumentoVenta.objects.create(tipo_documento='FA',fecha=self.hoy,cliente=self.cliente,
            tasa_bcv=10,impuesto=16,subtotal_usd=1,subtotal_bs=10,total_impuesto_bs=D('1.60'),total_bs=D('11.60'),registrado_por='prueba')
        with self.assertRaises(IntegrityError),transaction.atomic():
            DetalleVenta.objects.create(documento=doc,servicio=self.servicio,barbero=self.prestador,
                descripcion_barbero='Ana Pérez',codigo_servicio='S1',descripcion_servicio='Corte',cantidad_servicio=1,
                precio_unitario_usd=1,monto_servicio=1,monto_servicio_bs=10,monto_impuesto=D('1.60'))

    def test_proteccion_sql_rechaza_descuento_detalle_incorrecto(self):
        doc=DocumentoVenta.objects.create(tipo_documento='FA',fecha=self.hoy,cliente=self.cliente,
            tasa_bcv=10,impuesto=16,subtotal_usd=20,subtotal_bs=200,total_impuesto_bs=32,total_bs=232,
            descuento_porcentaje=50,descuento_usd=20,descuento_bs=200,registrado_por='prueba')
        with self.assertRaises(IntegrityError),transaction.atomic():
            DetalleVenta.objects.create(documento=doc,servicio=self.servicio,barbero=self.prestador,
                descripcion_barbero='Ana Pérez',codigo_servicio='S1',descripcion_servicio='Corte',cantidad_servicio=1,
                precio_unitario_usd=40,monto_servicio=40,monto_servicio_bs=400,monto_impuesto=32,
                monto_descuento_usd=1,monto_descuento_bs=10)

    def test_sellado_no_permite_cambiar_descuento(self):
        doc=DocumentoVenta.objects.create(tipo_documento='FA',fecha=self.hoy,cliente=self.cliente,
            tasa_bcv=10,impuesto=16,subtotal_usd=40,subtotal_bs=400,total_impuesto_bs=64,total_bs=464,registrado_por='prueba')
        with self.assertRaises(IntegrityError),transaction.atomic():
            with connection.cursor() as c:c.execute('UPDATE ventas_documentoventa SET descuento_porcentaje=50,sellado=1 WHERE id_documento=%s',[doc.pk])

    def test_redondeo_descuento_por_linea(self):
        doc=self.vender(servicio=self.manual,precio='0.05',descuento=True,monto='0.02')
        linea=doc.detalles.get()
        self.assertEqual(linea.monto_descuento_usd,D('0.03'))
        self.assertEqual(linea.monto_neto_usd,D('0.02'))
        self.assertEqual(linea.monto_neto_bs,D('0.20'))
        self.assertEqual(linea.monto_impuesto,D('0.03'))
        self.assertEqual(doc.total_bs,D('0.20'))

    def test_post_completo_descuento_manual(self):
        datos={'fecha':str(self.hoy),'cliente':self.cliente.pk,'clave':str(uuid.uuid4()),
            'aplicar_descuento':'on','descuento_porcentaje':'50',
            'lineas-TOTAL_FORMS':'1','lineas-INITIAL_FORMS':'0',
            'lineas-0-servicio':self.manual.pk,'lineas-0-barbero':self.prestador.pk,
            'lineas-0-cantidad_servicio':'1','lineas-0-precio_unitario_usd':'40.00',
            'pagos-TOTAL_FORMS':'1','pagos-INITIAL_FORMS':'0',
            'pagos-0-tipo_pago':'5','pagos-0-fecha':str(self.hoy),'pagos-0-monto':'20.00'}
        respuesta=self.client.post(reverse('ventas:crear'),datos)
        self.assertEqual(respuesta.status_code,302)
        doc=DocumentoVenta.objects.get()
        self.assertEqual(doc.total_bs,D('200.00'))
        self.assertEqual(doc.detalles.get().monto_servicio,D('40.00'))

    def test_post_descuento_total_sin_pagos(self):
        datos={'fecha':str(self.hoy),'cliente':self.cliente.pk,'clave':str(uuid.uuid4()),
            'aplicar_descuento':'on','descuento_porcentaje':'100',
            'lineas-TOTAL_FORMS':'1','lineas-INITIAL_FORMS':'0',
            'lineas-0-servicio':self.servicio.pk,'lineas-0-barbero':self.prestador.pk,'lineas-0-cantidad_servicio':'1',
            'pagos-TOTAL_FORMS':'0','pagos-INITIAL_FORMS':'0'}
        respuesta=self.client.post(reverse('ventas:crear'),datos)
        self.assertEqual(respuesta.status_code,302)
        self.assertEqual(DocumentoVenta.objects.get().total_bs,D('0.00'))

    def test_paginacion_facturas_conserva_filtros(self):
        for _ in range(26):self.vender()
        primera=self.client.get(reverse('ventas:lista'),{'tipo':'FA'})
        segunda=self.client.get(reverse('ventas:lista'),{'tipo':'FA','page':'2'})
        self.assertEqual(len(primera.context['pagina']),25)
        self.assertEqual(len(segunda.context['pagina']),1)
        self.assertContains(primera,'tipo=FA&amp;page=2')
        self.assertContains(segunda,'Página 2 de 2')
        self.assertFalse(set(d.pk for d in primera.context['pagina']) & set(d.pk for d in segunda.context['pagina']))
        self.assertEqual(self.client.get(reverse('ventas:lista'),{'page':'999'}).context['pagina'].number,2)
