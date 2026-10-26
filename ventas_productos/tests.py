import uuid
from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from clientes.models import Cliente
from tasas_bcv.models import TasaBCV
from inventario.models import Producto, Proveedor, Compra, DetalleCompra, UnidadMedida
from inventario.services import actualizar_compra
from inventario.existencias import existencia_producto
from .models import DocumentoProducto, LineaProducto, PagoProducto,PorcentajeProducto,EscalaDescuento
from .servicios import registrar_venta, registrar_reverso

class VentaProductosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario=get_user_model().objects.create_superuser(username="vendedor",password="prueba")
        cls.cliente=Cliente.objects.create(nombre="Cliente",apellido="Prueba",telefono="04121234567")
        for fecha in {date(2026,10,20),timezone.localdate()}:
            TasaBCV.objects.create(fecha=fecha,tasa_bcv=40)
        cls.producto=Producto.objects.create(codigo_producto="VP-1",nombre_producto="CHAMPÚ",
                     volumen=250,unidad_medida=UnidadMedida.objects.get(codigo="ML"))
        cls.otro=Producto.objects.create(codigo_producto="VP-2",nombre_producto="CERA")
        cls.proveedor=Proveedor.objects.create(nombre="PROVEEDOR",rif="J-VP")
        compra=Compra.objects.create(fecha_compra=date(2026,10,1),proveedor=cls.proveedor,numero_factura="STOCK-1",tasa_cambio=40,registrada_por="vendedor")
        DetalleCompra.objects.create(compra=compra,producto=cls.producto,cantidad=5,precio_unitario=4,tasa_impuesto=16)
        actualizar_compra(compra.pk,"vendedor",0)
        PorcentajeProducto.objects.create(producto=cls.producto,porcentaje=150)

    def setUp(self):
        self.client.force_login(self.usuario)

    def venta(self,**cambios):
        datos=dict(fecha=date(2026,10,20),cliente=self.cliente,
            lineas=[dict(producto=self.producto,cantidad=Decimal("2"),precio_unitario_usd=Decimal("10"))],
            pagos=[dict(tipo_pago="5",monto=Decimal("23.20"),fecha=date(2026,10,20))],
            clave=uuid.uuid4(),usuario=self.usuario,observacion="compra cliente")
        datos.update(cambios)
        return registrar_venta(**datos)

    def post(self,**cambios):
        datos={"fecha":"2026-10-20","cliente":self.cliente.pk,"clave":str(uuid.uuid4()),"observacion":"prueba",
          "lineas-TOTAL_FORMS":"1","lineas-INITIAL_FORMS":"0",
          "lineas-0-producto":self.producto.pk,"lineas-0-cantidad":"2","lineas-0-precio_unitario_usd":"10",
          "pagos-TOTAL_FORMS":"1","pagos-INITIAL_FORMS":"0",
          "pagos-0-tipo_pago":"5","pagos-0-fecha":"2026-10-20","pagos-0-monto":"23.20",
          "pagos-0-referencia":"ref","pagos-0-observacion":"pago"}
        datos.update(cambios)
        return datos

    def test_venta_descuenta_existencia_y_calcula(self):
        doc=self.venta()
        self.assertTrue(doc.sellado)
        self.assertEqual(doc.total_bs,Decimal("928"))
        self.assertEqual(doc.total_usd,Decimal("23.20"))
        self.assertEqual(doc.iva,Decimal("16"))
        self.assertEqual(doc.tasa_bcv,Decimal("40"))
        self.assertEqual(doc.observacion,"COMPRA CLIENTE")
        self.assertEqual(existencia_producto(self.producto.pk),Decimal("3"))
        self.assertEqual(doc.pagos.get().nombre_tipo_pago,"EFECTIVO")

    def test_web_guardar_y_documento(self):
        respuesta=self.client.post(reverse("ventas_productos:nueva"),self.post())
        self.assertEqual(respuesta.status_code,302)
        doc=DocumentoProducto.objects.get()
        self.assertRedirects(respuesta,reverse("ventas_productos:ver",args=[doc.pk]))
        self.assertContains(self.client.get(respuesta.url),f"VP-{doc.pk:06d}")

    def test_idempotencia_doble_envio(self):
        clave=uuid.uuid4()
        a=self.venta(clave=clave)
        b=self.venta(clave=clave)
        self.assertEqual(a.pk,b.pk)
        self.assertEqual(DocumentoProducto.objects.count(),1)
        self.assertEqual(existencia_producto(self.producto.pk),Decimal("3"))

    def test_no_permite_stock_insuficiente(self):
        with self.assertRaises(ValidationError):
            self.venta(lineas=[dict(producto=self.producto,cantidad=6,precio_unitario_usd=10)])
        self.assertFalse(DocumentoProducto.objects.exists())
        self.assertEqual(existencia_producto(self.producto.pk),Decimal("5"))

    def test_no_permite_producto_sin_compras_actualizadas(self):
        compra=Compra.objects.create(fecha_compra=date(2026,10,1),proveedor=self.proveedor,numero_factura="BORRADOR",tasa_cambio=40,registrada_por="vendedor")
        DetalleCompra.objects.create(compra=compra,producto=self.otro,cantidad=100,precio_unitario=1)
        with self.assertRaises(ValidationError):
            self.venta(lineas=[dict(producto=self.otro,cantidad=1,precio_unitario_usd=10)])
        self.assertEqual(existencia_producto(self.otro.pk),0)

    def test_stock_no_se_multiplica_con_varias_compras_y_ventas(self):
        compra=Compra.objects.create(fecha_compra=date(2026,10,1),proveedor=self.proveedor,numero_factura="STOCK-2",tasa_cambio=40,registrada_por="vendedor")
        DetalleCompra.objects.create(compra=compra,producto=self.producto,cantidad=3,precio_unitario=4)
        actualizar_compra(compra.pk,"vendedor",0)
        self.venta();self.venta()
        self.assertEqual(existencia_producto(self.producto.pk),Decimal("4"))

    def test_pagos_incompletos_o_excedidos_revierte_todo(self):
        for monto in ["23.19","23.21"]:
            with self.subTest(monto=monto):
                with self.assertRaises(ValidationError):
                    self.venta(pagos=[dict(tipo_pago="5",monto=Decimal(monto),fecha=date(2026,10,20))])
                self.assertFalse(DocumentoProducto.objects.exists())
                self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_pagos_mixtos(self):
        doc=self.venta(pagos=[
            dict(tipo_pago="5",monto=Decimal("10"),fecha=date(2026,10,20)),
            dict(tipo_pago="2",monto=Decimal("528"),fecha=date(2026,10,20))])
        self.assertEqual(doc.pagos.count(),2)
        self.assertEqual(sum((p.equivalente_bs for p in doc.pagos.all()),Decimal("0")),Decimal("928"))

    def test_sin_tasa_no_descuenta(self):
        with self.assertRaises(ValidationError):self.venta(fecha=date(2020,1,1))
        self.assertFalse(DocumentoProducto.objects.exists())
        self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_configuracion_compartida_fallida_no_guarda(self):
        from unittest.mock import patch
        with patch("inventario.condiciones.leer_impuesto",side_effect=ValueError("error")):
            respuesta=self.client.post(reverse("ventas_productos:nueva"),self.post())
        self.assertEqual(respuesta.status_code,200)
        self.assertFalse(DocumentoProducto.objects.exists())

    def test_precio_y_cantidad_invalidos(self):
        for cantidad,precio in [(0,10),(-1,10),(Decimal("0.0001"),10),(Decimal("0.001"),10)]:
            with self.subTest(cantidad=cantidad,precio=precio),self.assertRaises(ValidationError):
                self.venta(lineas=[dict(producto=self.producto,cantidad=cantidad,precio_unitario_usd=precio)])
        self.assertFalse(DocumentoProducto.objects.exists())

    def test_producto_repetido(self):
        linea=dict(producto=self.producto,cantidad=1,precio_unitario_usd=10)
        with self.assertRaises(ValidationError):self.venta(lineas=[linea,linea])
        self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_inactivos(self):
        self.producto.activo=False;self.producto.save()
        with self.assertRaises(ValidationError):self.venta()
        self.producto.activo=True;self.producto.save()
        self.cliente.activo=False;self.cliente.save()
        with self.assertRaises(ValidationError):self.venta()

    def test_no_se_vende_por_encima_de_lo_que_quedo(self):
        self.venta()
        with self.assertRaises(ValidationError):
            self.venta(lineas=[dict(producto=self.producto,cantidad=4,precio_unitario_usd=10)])
        self.assertEqual(existencia_producto(self.producto.pk),3)

    def test_reverso_repone_y_conserva_historial(self):
        original=self.venta()
        reverso=registrar_reverso(documento_id=original.pk,motivo="producto equivocado",usuario=self.usuario)
        self.assertEqual(reverso.tipo,"RP")
        self.assertEqual(reverso.total_bs,Decimal("-928"))
        self.assertEqual(reverso.total_usd,Decimal("-23.20"))
        self.assertEqual(reverso.pagos.get().monto,Decimal("-23.20"))
        self.assertEqual(existencia_producto(self.producto.pk),5)
        self.assertEqual(DocumentoProducto.objects.count(),2)
        self.assertEqual(reverso.motivo,"PRODUCTO EQUIVOCADO")

    def test_reverso_una_vez_y_no_reversa_otro_reverso(self):
        original=self.venta()
        reverso=registrar_reverso(documento_id=original.pk,motivo="CORRECCIÓN",usuario=self.usuario)
        with self.assertRaises(ValidationError):registrar_reverso(documento_id=original.pk,motivo="OTRO",usuario=self.usuario)
        with self.assertRaises(ValidationError):registrar_reverso(documento_id=reverso.pk,motivo="OTRO",usuario=self.usuario)
        self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_reverso_usa_valores_originales_sin_bcv_del_dia(self):
        original=self.venta()
        self.producto.activo=False;self.producto.save()
        self.cliente.activo=False;self.cliente.save()
        TasaBCV.objects.all().delete()
        reverso=registrar_reverso(documento_id=original.pk,motivo="CORRECCIÓN",usuario=self.usuario)
        self.assertEqual(reverso.tasa_bcv,40)
        self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_snapshot_producto_cliente(self):
        doc=self.venta()
        self.producto.nombre_producto="OTRO NOMBRE";self.producto.save()
        self.cliente.nombre="OTRO CLIENTE";self.cliente.save()
        doc.refresh_from_db()
        self.assertIn("CHAMPÚ",doc.detalles.get().descripcion)
        self.assertEqual(doc.descripcion_cliente,"CLIENTE PRUEBA")

    def test_bloqueo_sql_documento_detalle_pago(self):
        doc=self.venta()
        for tabla in ["documentoproducto","lineaproducto","pagoproducto"]:
            for operacion in ["UPDATE","DELETE"]:
                with self.subTest(tabla=tabla,operacion=operacion):
                    with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
                        sql=f"UPDATE ventas_productos_{tabla} SET id=id" if operacion=="UPDATE" else f"DELETE FROM ventas_productos_{tabla}"
                        cursor.execute(sql)

    def test_no_agrega_lineas_ni_pagos_a_sellado(self):
        doc=self.venta()
        with self.assertRaises(ValidationError):
            LineaProducto.objects.create(documento=doc,producto=self.otro,codigo="X",descripcion="X",
                 cantidad=1,precio_unitario_usd=1,subtotal_usd=1,subtotal_bs=40,impuesto_bs=0)
        with self.assertRaises(ValidationError):doc.save()

    def test_sql_impide_sello_sin_existencias(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            doc=DocumentoProducto.objects.create(tipo="VP",fecha=date(2026,10,20),cliente=self.cliente,
                descripcion_cliente="CLIENTE",tasa_bcv=40,iva=16,subtotal_usd=60,subtotal_bs=2400,
                impuesto_bs=384,total_bs=2784,registrado_por="vendedor")
            LineaProducto.objects.create(documento=doc,producto=self.producto,descripcion="X",codigo="VP-1",
                cantidad=6,precio_unitario_usd=10,subtotal_usd=60,subtotal_bs=2400,impuesto_bs=384)
            PagoProducto.objects.create(documento=doc,tipo_pago=5,nombre_tipo_pago="EFECTIVO",moneda="USD",
                fecha=date(2026,10,20),monto=Decimal("69.60"),equivalente_bs=2784)
            DocumentoProducto.objects.filter(pk=doc.pk).update(sellado=True)
        self.assertEqual(existencia_producto(self.producto.pk),5)

    def test_web_no_confia_en_bcv_iva_ni_stock_enviado(self):
        respuesta=self.client.post(reverse("ventas_productos:nueva"),self.post(tasa_bcv="1",iva="0",existencia="999"))
        self.assertEqual(respuesta.status_code,302)
        doc=DocumentoProducto.objects.get()
        self.assertEqual((doc.tasa_bcv,doc.iva),(Decimal("40"),Decimal("16")))

    def test_web_filtros_paginacion_y_pantallas(self):
        doc=self.venta()
        for ruta in ["lista","nueva"]:
            self.assertEqual(self.client.get(reverse("ventas_productos:"+ruta)).status_code,200)
        for ruta in ["ver","reversar"]:
            self.assertEqual(self.client.get(reverse("ventas_productos:"+ruta,args=[doc.pk])).status_code,200)
        for filtro in [{"numero":doc.pk},{"cliente":"cliente"},{"producto":"CHAMPÚ"},{"desde":"2026-10-20","hasta":"2026-10-20"}]:
            self.assertEqual(len(self.client.get(reverse("ventas_productos:lista"),filtro).context["pagina"]),1)
        respuesta=self.client.get(reverse("ventas_productos:lista"),{"desde":"2026-11-01","hasta":"2026-01-01"})
        self.assertContains(respuesta,"La fecha desde")

    def test_buscador_y_consulta_muestran_stock_neto(self):
        self.venta()
        datos=self.client.get(reverse("inventario:buscar_productos"),{"q":"VP-1"}).json()
        self.assertEqual(Decimal(datos["resultados"][0]["existencia"]),3)
        respuesta=self.client.get(reverse("inventario:productos"),{"q":"VP-1"})
        self.assertEqual(respuesta.context["pagina"][0].existencia,3)

    def test_boton_nuevo_producto_solo_en_consulta(self):
        for ruta in ["inventario:compras","inventario:nueva_compra"]:
            self.assertNotContains(self.client.get(reverse(ruta)),">Nuevo producto</a>")
        self.assertContains(self.client.get(reverse("inventario:productos")),">Nuevo producto</a>")

    def test_seguridad_autenticacion_csrf_y_get_reverso(self):
        sin_sesion=Client()
        self.assertEqual(sin_sesion.get(reverse("ventas_productos:lista")).status_code,302)
        seguro=Client(enforce_csrf_checks=True);seguro.force_login(self.usuario)
        self.assertEqual(seguro.post(reverse("ventas_productos:nueva"),self.post()).status_code,403)
        doc=self.venta()
        self.client.get(reverse("ventas_productos:reversar",args=[doc.pk]))
        self.assertEqual(DocumentoProducto.objects.count(),1)

    def test_importe_minimo_y_stock_fraccionario_sin_errores_de_redondeo(self):
        with self.assertRaises(ValidationError):
            self.venta(lineas=[dict(producto=self.producto,cantidad=Decimal("0.001"),precio_unitario_usd=Decimal("0.01"))])
        producto=Producto.objects.create(codigo_producto="FRAC",nombre_producto="FRACCIONARIO")
        compra=Compra.objects.create(fecha_compra=date(2026,10,1),proveedor=self.proveedor,numero_factura="FRAC",tasa_cambio=40,registrada_por="vendedor")
        DetalleCompra.objects.create(compra=compra,producto=producto,cantidad=Decimal("0.3"),precio_unitario=1)
        actualizar_compra(compra.pk,"vendedor",0)
        PorcentajeProducto.objects.create(producto=producto,porcentaje=9900)
        self.venta(lineas=[dict(producto=producto,cantidad=Decimal("0.1"),precio_unitario_usd=100)],
                   pagos=[dict(tipo_pago="5",monto=Decimal("11.60"),fecha=date(2026,10,20))])
        self.venta(lineas=[dict(producto=producto,cantidad=Decimal("0.2"),precio_unitario_usd=100)])
        self.assertEqual(existencia_producto(producto.pk),0)

    def test_paginacion_conserva_filtros(self):
        compra=Compra.objects.create(fecha_compra=date(2026,10,1),proveedor=self.proveedor,numero_factura="MAS-STOCK",tasa_cambio=40,registrada_por="vendedor")
        DetalleCompra.objects.create(compra=compra,producto=self.producto,cantidad=30,precio_unitario=4)
        actualizar_compra(compra.pk,"vendedor",0)
        for _ in range(26):
            self.venta(lineas=[dict(producto=self.producto,cantidad=1,precio_unitario_usd=1)],
                       pagos=[dict(tipo_pago="5",monto=Decimal("11.60"),fecha=date(2026,10,20))])
        respuesta=self.client.get(reverse("ventas_productos:lista"),{"cliente":"CLIENTE","page":2})
        self.assertEqual(len(respuesta.context["pagina"]),1)
        self.assertContains(respuesta,"cliente=CLIENTE")
        self.assertContains(respuesta,"Página 2 de 2")

    def test_no_genera_ventas_de_servicios_ni_comisiones(self):
        from ventas.models import DocumentoVenta,DetalleVenta
        documentos,detalles=DocumentoVenta.objects.count(),DetalleVenta.objects.count()
        self.venta()
        self.assertEqual(DocumentoVenta.objects.count(),documentos)
        self.assertEqual(DetalleVenta.objects.count(),detalles)

    def test_sql_rechaza_reverso_con_cantidad_alterada(self):
        original=self.venta()
        with self.assertRaises(IntegrityError),transaction.atomic():
            doc=DocumentoProducto.objects.create(tipo="RP",fecha=date(2026,10,20),cliente=self.cliente,
                descripcion_cliente="CLIENTE",tasa_bcv=40,iva=16,subtotal_usd=-20,subtotal_bs=-800,
                impuesto_bs=-128,total_bs=-928,registrado_por="vendedor",documento_original=original,motivo="ERROR")
            LineaProducto.objects.create(documento=doc,producto=self.producto,codigo="VP-1",descripcion="X",
                cantidad=3,precio_unitario_usd=10,subtotal_usd=-20,subtotal_bs=-800,impuesto_bs=-128,
                linea_original=original.detalles.get())
            PagoProducto.objects.create(documento=doc,tipo_pago=5,nombre_tipo_pago="EFECTIVO",moneda="USD",
                fecha=date(2026,10,20),monto=Decimal("-23.20"),equivalente_bs=-928,pago_original=original.pagos.get())
            DocumentoProducto.objects.filter(pk=doc.pk).update(sellado=True)
        self.assertEqual(existencia_producto(self.producto.pk),3)
