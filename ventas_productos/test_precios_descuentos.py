import uuid
from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError,transaction
from django.urls import reverse
from clientes.models import Cliente
from tasas_bcv.models import TasaBCV
from inventario.models import Producto,Proveedor,Compra,DetalleCompra
from inventario.forms import ProductoForm,DetalleForm
from inventario.services import actualizar_compra
from inventario.existencias import existencia_producto
from control_inventario.forms import LineaAjusteForm,ConteoForm
from .forms import LineaForm,EscalaForm,PorcentajeForm
from .models import DocumentoProducto,PorcentajeProducto,EscalaDescuento
from .precios import precio_producto
from .servicios import registrar_venta,registrar_reverso

class PreciosDescuentosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario=get_user_model().objects.create_user(username="precios",password="prueba")
        cls.cliente=Cliente.objects.create(nombre="CLIENTE",apellido="PRECIOS",telefono="04121234567")
        cls.a=Producto.objects.create(codigo_producto="PR-A",nombre_producto="PRODUCTO A")
        cls.b=Producto.objects.create(codigo_producto="PR-B",nombre_producto="PRODUCTO B")
        cls.proveedor=Proveedor.objects.create(nombre="PROVEEDOR",rif="J-PRECIOS")
        compra=Compra.objects.create(proveedor=cls.proveedor,numero_factura="PRECIOS",fecha_compra=date(2026,10,1),tasa_cambio=40,registrada_por="precios")
        for producto in [cls.a,cls.b]:DetalleCompra.objects.create(compra=compra,producto=producto,cantidad=200,precio_unitario=10)
        actualizar_compra(compra.pk,"precios",0)
        PorcentajeProducto.objects.create(producto=cls.a,porcentaje=50)
        PorcentajeProducto.objects.create(producto=cls.b,porcentaje=100)
        TasaBCV.objects.create(fecha=date(2026,10,20),tasa_bcv=40)

    def setUp(self):self.client.force_login(self.usuario)
    def regla(self,nivel=1,umbral=2,porcentaje=10):
        return EscalaDescuento.objects.create(nivel=nivel,unidades_mayor_que=umbral,porcentaje=porcentaje)
    def venta(self,cantidad=2,pago="34.80",filas=None,clave=None):
        return registrar_venta(fecha=date(2026,10,20),cliente=self.cliente,
            lineas=filas or [dict(producto=self.a,cantidad=Decimal(str(cantidad)),precio_unitario_usd=Decimal("999"))],
            pagos=[] if pago is None else [dict(tipo_pago="5",fecha=date(2026,10,20),monto=Decimal(pago))],
            clave=clave or uuid.uuid4(),usuario=self.usuario)

    def test_recargo_confirmado_costo10_mas50_da15(self):
        precio=precio_producto(self.a,date(2026,10,20))
        self.assertEqual(precio["costo_unitario_usd"],Decimal("10.00"))
        self.assertEqual(precio["precio_unitario_usd"],Decimal("15.00"))
        doc=self.venta()
        self.assertEqual(doc.detalles.get().precio_unitario_usd,15)
        self.assertEqual(doc.total_usd,Decimal("34.80"))

    def test_precio_enviado_manualmente_no_modifica_el_real(self):
        doc=self.venta(filas=[dict(producto=self.a,cantidad=2,precio_unitario_usd=Decimal("0.01"))])
        self.assertEqual(doc.detalles.get().precio_unitario_usd,15)

    def test_regla_inexistente_o_inactiva_impide_vender(self):
        regla=PorcentajeProducto.objects.get(producto=self.a)
        regla.activo=False;regla.save()
        with self.assertRaises(ValidationError):self.venta()
        self.assertFalse(DocumentoProducto.objects.exists())
        self.assertEqual(existencia_producto(self.a.pk),200)

    def test_sin_costo_no_inventa_precio(self):
        producto=Producto.objects.create(codigo_producto="SIN-COSTO",nombre_producto="SIN COSTO")
        PorcentajeProducto.objects.create(producto=producto,porcentaje=50)
        with self.assertRaises(ValidationError):precio_producto(producto,date(2026,10,20))

    def test_recargo_cero_vende_a_costo(self):
        PorcentajeProducto.objects.filter(producto=self.a).update(porcentaje=0)
        self.assertEqual(precio_producto(self.a,date(2026,10,20))["precio_unitario_usd"],10)

    def test_umbral_es_mayor_o_igual(self):
        self.regla()
        exacto=self.venta(2,"31.32")
        mayor=self.venta(3,"46.98")
        self.assertEqual(exacto.descuento_porcentaje,10)
        self.assertEqual(mayor.descuento_porcentaje,10)
        self.assertEqual(mayor.descuento_usd,Decimal("4.50"))
        self.assertEqual(mayor.base_usd,Decimal("40.50"))
        self.assertEqual(mayor.impuesto_bs,Decimal("259.20"))
        self.assertEqual(mayor.total_bs,Decimal("1879.20"))

    def test_cuatro_tramos_elige_el_mayor_sin_acumular(self):
        for n,u,p in [(1,2,10),(2,4,15),(3,6,20),(4,8,25)]:self.regla(n,u,p)
        doc=self.venta(9,"117.45")
        self.assertEqual((doc.descuento_nivel,doc.umbral_descuento,doc.descuento_porcentaje),(4,8,25))
        self.assertEqual(doc.descuento_usd,Decimal("33.75"))
        self.assertEqual(doc.impuesto_bs,Decimal("648"))
        self.assertEqual(doc.total_bs,Decimal("4698"))

    def test_cantidad_total_de_todos_los_productos(self):
        self.regla()
        doc=self.venta(pago="52.20",filas=[dict(producto=self.a,cantidad=2),dict(producto=self.b,cantidad=1)])
        self.assertEqual(doc.unidades_total,3)
        self.assertEqual(doc.descuento_porcentaje,10)
        self.assertEqual(doc.subtotal_usd,50)
        self.assertEqual(doc.descuento_usd,5)
        self.assertEqual(list(doc.detalles.values_list("descuento_usd",flat=True)),[Decimal("3"),Decimal("2")])

    def test_exactamente_umbral_superior_usa_nuevo_tramo(self):
        self.regla(1,2,10);self.regla(2,4,15)
        doc=self.venta(4,"59.16")
        self.assertEqual(doc.descuento_nivel,2)

    def test_tramo_inactivo_no_se_aplica(self):
        r=self.regla();r.activo=False;r.save()
        self.assertEqual(self.venta().descuento_porcentaje,0)

    def test_descuento100_cero_sin_pagos_y_reverso(self):
        self.regla(1,0,100)
        doc=self.venta(1,None)
        self.assertEqual(doc.total_bs,0)
        self.assertEqual(doc.descuento_usd,15)
        self.assertEqual(doc.impuesto_bs,0)
        self.assertFalse(doc.pagos.exists())
        self.assertEqual(existencia_producto(self.a.pk),199)
        reverso=registrar_reverso(documento_id=doc.pk,motivo="PRUEBA",usuario=self.usuario)
        self.assertEqual(reverso.descuento_usd,-15)
        self.assertEqual(reverso.total_bs,0)
        self.assertEqual(existencia_producto(self.a.pk),200)

    def test_total_cero_no_admite_pagos(self):
        self.regla(1,0,100)
        with self.assertRaises(ValidationError):self.venta(1,"0.01")
        self.assertFalse(DocumentoProducto.objects.exists())

    def test_reverso_preserva_precio_descuento_iva_anteriores(self):
        self.regla()
        doc=self.venta(3,"46.98")
        PorcentajeProducto.objects.filter(producto=self.a).update(porcentaje=300)
        EscalaDescuento.objects.all().update(porcentaje=50)
        TasaBCV.objects.all().update(tasa_bcv=100)
        re=registrar_reverso(documento_id=doc.pk,motivo="CORRECCIÓN",usuario=self.usuario)
        self.assertEqual(re.tasa_bcv,40)
        self.assertEqual(re.descuento_porcentaje,10)
        self.assertEqual(re.descuento_usd,Decimal("-4.50"))
        self.assertEqual(re.impuesto_bs,Decimal("-259.20"))
        self.assertEqual(re.total_bs,Decimal("-1879.20"))
        self.assertEqual(re.detalles.get().porcentaje_venta,50)
        self.assertEqual(re.detalles.get().costo_unitario_usd,10)
        self.assertEqual(existencia_producto(self.a.pk),200)

    def test_reenvio_con_configuracion_cambiada_no_duplica(self):
        clave=uuid.uuid4()
        doc=self.venta(clave=clave)
        PorcentajeProducto.objects.filter(producto=self.a).update(porcentaje=300)
        self.assertEqual(self.venta(clave=clave).pk,doc.pk)
        self.assertEqual(existencia_producto(self.a.pk),198)

    def test_costo_y_precio_redondeados_a_dos(self):
        compra=Compra.objects.create(proveedor=self.proveedor,numero_factura="REDONDEO",fecha_compra=date(2026,10,2),divisa="BS",tasa_cambio=10,registrada_por="precios")
        DetalleCompra.objects.create(compra=compra,producto=self.a,cantidad=1,precio_unitario=Decimal("123.46"))
        actualizar_compra(compra.pk,"precios",0)
        datos=precio_producto(self.a,date(2026,10,20))
        self.assertEqual(datos["costo_unitario_usd"],Decimal("12.35"))
        self.assertEqual(datos["precio_unitario_usd"],Decimal("18.53"))

    def test_nuevas_cantidades_y_fisicos_solo_dos_decimales(self):
        for clase,datos,campo in [
            (LineaForm,{"producto":self.a.pk,"cantidad":"1.001"},"cantidad"),
            (LineaAjusteForm,{"producto":self.a.pk,"cantidad":"1.001"},"cantidad"),
            (ConteoForm,{"renglon":1,"fisico":"1.001"},"fisico"),
            (DetalleForm,{"producto":self.a.pk,"cantidad":"1.001","precio_unitario":"10"},"cantidad"),
            (DetalleForm,{"producto":self.a.pk,"cantidad":"1","precio_unitario":"10.001"},"precio_unitario"),
        ]:
            with self.subTest(clase=clase,campo=campo):
                form=clase(datos);self.assertFalse(form.is_valid());self.assertIn(campo,form.errors)

    def test_tablas_y_limite_de_cuatro_niveles(self):
        self.assertFalse(EscalaForm({"nivel":5,"unidades_mayor_que":1,"porcentaje":10,"activo":"on"}).is_valid())
        self.assertFalse(EscalaForm({"nivel":1,"unidades_mayor_que":1,"porcentaje":101,"activo":"on"}).is_valid())
        self.assertFalse(PorcentajeForm({"producto":self.a.pk,"porcentaje":-1,"activo":"on"}).is_valid())
        self.regla()
        self.assertFalse(EscalaForm({"nivel":2,"unidades_mayor_que":2,"porcentaje":10,"activo":"on"}).is_valid())
        with self.assertRaises(IntegrityError),transaction.atomic():
            self.regla(5,5,10)

    def test_captura_configuracion_y_precio_lectura(self):
        r=self.client.get(reverse("ventas_productos:precio"),{"producto":self.a.pk,"fecha":"2026-10-20"})
        self.assertEqual(r.json()["precio_unitario_usd"],"15.00")
        for ruta in ["porcentajes","descuentos","nuevo_porcentaje","nuevo_descuento"]:
            self.assertEqual(self.client.get(reverse("ventas_productos:"+ruta)).status_code,200)
        r=self.client.post(reverse("ventas_productos:nuevo_descuento"),
            {"nivel":1,"unidades_mayor_que":"2.00","porcentaje":"10.00","activo":"on"})
        self.assertEqual(r.status_code,302)
        r=self.client.get(reverse("ventas_productos:nueva"))
        self.assertContains(r,'class="form-control precio-automatico"')
        self.assertNotContains(r,'name="lineas-0-precio_unitario_usd"')

    def test_factura_muestra_descuento_iva_y_total(self):
        self.regla();doc=self.venta(3,"46.98")
        r=self.client.get(reverse("ventas_productos:ver",args=[doc.pk]))
        for texto in ["Subtotal","Descuento 10.00 %","Base imponible","IVA 16.00 %","Total general","Equivalente USD"]:
            self.assertContains(r,texto)

    def test_factura_sin_descuento_omite_renglon_de_descuento(self):
        doc=self.venta()
        r=self.client.get(reverse("ventas_productos:ver",args=[doc.pk]))
        self.assertNotContains(r,"<th>Descuento")
        self.assertContains(r,"IVA 16.00 %")

    def test_compras_sin_accesos_duplicados(self):
        from django.contrib.auth.models import Permission
        self.usuario.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventario",codename="view_compra"),
            Permission.objects.get(content_type__app_label="control_inventario",codename="view_movimientostock"))
        r=self.client.get(reverse("inventario:compras"))
        self.assertContains(r,">Compras</a>")
        for texto in [">Consulta de stock</a>",">Otras entradas / salidas</a>",">Cierres mensuales</a>"]:
            self.assertNotContains(r,texto)
        self.assertContains(r,">Control de inventario</a>")

    def test_cantidad_fraccionaria_compara_umbral_sin_error_binario(self):
        self.regla(1,Decimal("0.30"),10)
        doc=self.venta(pago="5.74",filas=[dict(producto=self.a,cantidad=Decimal("0.10")),dict(producto=self.b,cantidad=Decimal("0.20"))])
        self.assertEqual(doc.unidades_total,Decimal("0.30"))
        self.assertEqual(doc.descuento_porcentaje,10)

    def test_borrador_antiguo_con_mas_decimales_debe_revisarse(self):
        compra=Compra.objects.create(proveedor=self.proveedor,numero_factura="BORRADOR-ANTERIOR",
            fecha_compra=date(2026,10,2),tasa_cambio=40,registrada_por="precios")
        DetalleCompra.objects.create(compra=compra,producto=self.a,cantidad=Decimal("1.001"),precio_unitario=10)
        with self.assertRaises(ValidationError):
            actualizar_compra(compra.pk,"precios",0)
        compra.refresh_from_db()
        self.assertEqual(compra.estado,"B")

    def test_conteo_antiguo_con_mas_decimales_debe_revisarse(self):
        from unittest.mock import patch
        from control_inventario.servicios import iniciar_cierre,confirmar_cierre
        with patch("control_inventario.servicios.timezone.localdate",return_value=date(2026,11,1)):
            cierre=iniciar_cierre(periodo=date(2026,10,1),observacion="",usuario="precios")
        cierre.detalles.update(fisico=Decimal("200.001"))
        with self.assertRaises(ValidationError):
            confirmar_cierre(cierre_id=cierre.pk,revision=0,usuario="precios")
        cierre.refresh_from_db()
        self.assertEqual(cierre.estado,"B")

    def test_limites_10_y_20_unidades_inclusivos(self):
        from .precios import descuento_para
        self.regla(1,10,5);self.regla(2,20,10)
        self.assertIsNone(descuento_para(Decimal("9.99")))
        self.assertEqual(descuento_para(Decimal("10")).nivel,1)
        self.assertEqual(descuento_para(Decimal("19.99")).nivel,1)
        self.assertEqual(descuento_para(Decimal("20")).nivel,2)

    def test_formato_miles_y_consulta_compacta(self):
        from ventas.templatetags.ventas_formato import monto_venta
        from inventario.forms import FiltroCompras
        self.assertEqual(monto_venta(Decimal("1234567.5")),"1,234,567.50")
        self.assertEqual(monto_venta(Decimal("-1234.56")),"-1,234.56")
        self.assertEqual(FiltroCompras().fields["proveedor"].label_from_instance(self.proveedor), self.proveedor.nombre)
        r=self.client.get(reverse("inventario:compras"))
        self.assertNotContains(r,"Factura / Control")
        self.assertNotContains(r,self.proveedor.rif)
        r=self.client.get(reverse("ventas_productos:porcentajes"))
        self.assertNotContains(r,"Precio USD =")
        self.assertNotContains(r,"Ejemplo: costo")
