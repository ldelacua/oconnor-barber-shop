from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from .models import Producto, Proveedor, Compra, DetalleCompra, MovimientoInventario, UnidadMedida
from .forms import CompraForm, DetalleFormSet, ProductoForm, ProveedorForm
from .services import actualizar_compra, eliminar_borrador

class InventarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tasas_bcv.models import TasaBCV
        from django.utils import timezone
        for fecha in {date(2026, 10, 20), timezone.localdate()}:
            TasaBCV.objects.create(fecha=fecha, tasa_bcv=40)
        cls.unidad = UnidadMedida.objects.get(codigo="GR")
        cls.usuario = get_user_model().objects.create_superuser(username="inventario", password="prueba")
        cls.proveedor = Proveedor.objects.create(nombre="Proveedor uno", rif="J-1")
        cls.otro_proveedor = Proveedor.objects.create(nombre="Proveedor dos", rif="J-2")
        cls.producto = Producto.objects.create(codigo_producto="P-1", nombre_producto="Champú", modelo="250 ml")
        cls.otro_producto = Producto.objects.create(codigo_producto="P-2", nombre_producto="Cera")

    def setUp(self):
        self.client.force_login(self.usuario)

    def compra(self, factura="F-1", divisa="USD", proveedor=None):
        compra = Compra.objects.create(proveedor=proveedor or self.proveedor, numero_factura=factura,
                 fecha_compra=date(2026, 10, 20), divisa=divisa, tasa_cambio=Decimal("40"), registrada_por="inventario")
        DetalleCompra.objects.create(compra=compra, producto=self.producto,
             cantidad=Decimal("3"), precio_unitario=Decimal("10"), tasa_impuesto=Decimal("16"))
        return compra

    def datos(self, compra=None, **kwargs):
        datos = {
          "proveedor": self.proveedor.pk, "numero_factura": "FACT-1", "numero_control": "C-1",
          "fecha_compra": "2026-10-20", "divisa": "USD", "tasa_cambio": "40",
          "observacion": "Prueba", "version": compra.revision if compra else 0,
          "detalles-TOTAL_FORMS": "1", "detalles-INITIAL_FORMS": "1" if compra else "0",
          "detalles-MIN_NUM_FORMS": "1", "detalles-MAX_NUM_FORMS": "200",
          "detalles-0-producto": self.producto.pk, "detalles-0-cantidad": "3",
          "detalles-0-precio_unitario": "10", "detalles-0-tasa_impuesto": "16",
        }
        if compra: datos["detalles-0-id"] = compra.detalles.get().pk
        datos.update(kwargs)
        return datos

    def test_precio_unitario_impuesto(self):
        compra = self.compra()
        self.assertEqual(compra.subtotal, Decimal("30.00"))
        self.assertEqual(compra.impuesto, Decimal("4.80"))
        self.assertEqual(compra.total, Decimal("34.80"))
        self.assertEqual(compra.total_bs, Decimal("1392.00"))

    def test_conversion_bs(self):
        compra = self.compra(divisa="BS")
        self.assertEqual(compra.total_usd, Decimal("0.87"))
        actualizar_compra(compra.pk, "inventario", 0)
        self.assertEqual(MovimientoInventario.objects.get().costo_unitario_usd, Decimal("0.25000000"))

    def test_borrador_no_suma_y_actualizacion_una_vez(self):
        compra = self.compra()
        self.assertEqual(MovimientoInventario.objects.count(), 0)
        self.assertTrue(actualizar_compra(compra.pk, "inventario", 0))
        self.assertFalse(actualizar_compra(compra.pk, "inventario", 0))
        self.assertEqual(MovimientoInventario.objects.count(), 1)
        self.assertEqual(MovimientoInventario.objects.get().cantidad, Decimal("3"))
        self.assertEqual(self.client.get(reverse("inventario:productos")).context["pagina"][0].existencia, Decimal("3"))

    def test_guardar_borrador_web_y_editar(self):
        respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos())
        self.assertEqual(respuesta.status_code, 302)
        compra = Compra.objects.get()
        self.assertEqual(compra.estado, "B")
        self.assertEqual(MovimientoInventario.objects.count(), 0)
        datos = self.datos(compra, **{"detalles-0-cantidad": "5"})
        respuesta = self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)
        compra.refresh_from_db()
        self.assertEqual(compra.revision, 1)
        self.assertEqual(compra.detalles.get().cantidad, Decimal("5"))

    def test_factura_unica_por_proveedor(self):
        self.compra(factura="FACT-1")
        respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos(numero_factura=" fact-1 "))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors)
        self.assertEqual(Compra.objects.count(), 1)
        datos = self.datos(proveedor=self.otro_proveedor.pk)
        self.assertEqual(self.client.post(reverse("inventario:nueva_compra"), datos).status_code, 302)

    def test_formulario_factura_repetida_en_edicion(self):
        compra = self.compra(factura="FACT-1")
        respuesta = self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), self.datos(compra))
        self.assertEqual(respuesta.status_code, 302)

    def test_no_hay_actualizacion_por_get(self):
        compra = self.compra()
        self.assertEqual(self.client.get(reverse("inventario:actualizar", args=[compra.pk])).status_code, 405)
        self.assertFalse(MovimientoInventario.objects.exists())

    def test_bloqueo_web(self):
        compra = self.compra()
        actualizar_compra(compra.pk, "inventario", 0)
        self.assertEqual(self.client.post(reverse("inventario:editar_compra", args=[compra.pk]),
                                         self.datos(compra)).status_code, 302)
        self.client.post(reverse("inventario:eliminar", args=[compra.pk]), {"revision": 1})
        self.assertTrue(Compra.objects.filter(pk=compra.pk).exists())

    def test_bloqueo_modelo(self):
        compra = self.compra()
        actualizar_compra(compra.pk, "inventario", 0)
        with self.assertRaises(ValidationError): compra.save()
        with self.assertRaises(ValidationError): compra.delete()
        detalle = compra.detalles.get()
        with self.assertRaises(ValidationError): detalle.save()
        with self.assertRaises(ValidationError): detalle.delete()

    def test_bloqueo_sql_cabecera_y_detalle_y_movimiento(self):
        compra = self.compra()
        actualizar_compra(compra.pk, "inventario", 0)
        consultas = [
            ("UPDATE inventario_compra SET observacion='cambio' WHERE id_compra=%s", compra.pk),
            ("DELETE FROM inventario_compra WHERE id_compra=%s", compra.pk),
            ("UPDATE inventario_detallecompra SET cantidad=7 WHERE compra_id=%s", compra.pk),
            ("DELETE FROM inventario_detallecompra WHERE compra_id=%s", compra.pk),
            ("UPDATE inventario_movimientoinventario SET cantidad=7 WHERE detalle_id=%s", compra.detalles.get().pk),
            ("DELETE FROM inventario_movimientoinventario WHERE detalle_id=%s", compra.detalles.get().pk),
        ]
        for sql, pk in consultas:
            with self.subTest(sql=sql):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor: cursor.execute(sql, [pk])

    def test_no_agrega_detalle_a_actualizada(self):
        compra = self.compra()
        actualizar_compra(compra.pk, "inventario", 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleCompra.objects.bulk_create([DetalleCompra(compra=compra, producto=self.otro_producto,
               cantidad=1, precio_unitario=1, tasa_impuesto=0)])

    def test_no_reasigna_detalle_actualizado(self):
        compra = self.compra()
        otra = self.compra(factura="OTRA")
        detalle = compra.detalles.get()
        actualizar_compra(compra.pk, "inventario", 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleCompra.objects.filter(pk=detalle.pk).update(compra=otra)

    def test_no_actualiza_sin_movimientos(self):
        compra = self.compra()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Compra.objects.filter(pk=compra.pk).update(estado="A")

    def test_actualizacion_vacia_se_revierte(self):
        compra = Compra.objects.create(proveedor=self.proveedor, numero_factura="VACIA",
                         tasa_cambio=1, registrada_por="inventario")
        with self.assertRaises(ValidationError): actualizar_compra(compra.pk, "inventario", 0)
        compra.refresh_from_db()
        self.assertEqual(compra.revision, 0)

    def test_producto_inactivo_actualizacion_atomica(self):
        compra = self.compra()
        self.otro_producto.activo = False
        self.otro_producto.save()
        DetalleCompra.objects.create(compra=compra, producto=self.otro_producto, cantidad=1,
                                     precio_unitario=5, tasa_impuesto=0)
        with self.assertRaises(ValidationError): actualizar_compra(compra.pk, "inventario", 0)
        self.assertFalse(MovimientoInventario.objects.exists())
        compra.refresh_from_db()
        self.assertEqual((compra.estado, compra.revision), ("B", 0))

    def test_proveedor_inactivo(self):
        compra = self.compra()
        self.proveedor.activo = False
        self.proveedor.save()
        with self.assertRaises(ValidationError): actualizar_compra(compra.pk, "inventario", 0)

    def test_revision_obsoleta_no_sobrescribe(self):
        compra = self.compra()
        Compra.objects.filter(pk=compra.pk).update(revision=1)
        respuesta = self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), self.datos(compra))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "La compra cambió")
        self.assertEqual(compra.detalles.get().cantidad, Decimal("3"))
        with self.assertRaises(ValidationError): actualizar_compra(compra.pk, "inventario", 0)
        with self.assertRaises(ValidationError): eliminar_borrador(compra.pk, 0)

    def test_eliminar_borrador(self):
        compra = self.compra()
        eliminar_borrador(compra.pk, 0)
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(DetalleCompra.objects.exists())

    def test_valores_invalidos(self):
        for campo, valor in [("divisa", "EUR"),
             ("detalles-0-cantidad", "0"), ("detalles-0-precio_unitario", "-1")]:
            with self.subTest(campo=campo, valor=valor):
                respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos(**{campo: valor}))
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(Compra.objects.exists())

    def test_detalles_vacios_y_duplicados(self):
        datos = self.datos(**{"detalles-0-DELETE": "on"})
        self.assertEqual(self.client.post(reverse("inventario:nueva_compra"), datos).status_code, 200)
        datos = self.datos(**{"detalles-TOTAL_FORMS": "2", "detalles-1-producto": self.producto.pk,
                 "detalles-1-cantidad": "2", "detalles-1-precio_unitario": "5", "detalles-1-tasa_impuesto": "0"})
        self.assertEqual(self.client.post(reverse("inventario:nueva_compra"), datos).status_code, 200)
        self.assertFalse(Compra.objects.exists())

    def test_filtros(self):
        compra = self.compra(factura="AB-123")
        self.compra(factura="CD-567", proveedor=self.otro_proveedor)
        for filtro in [
            {"proveedor": self.proveedor.pk}, {"factura": "AB-"},
            {"desde": "2026-10-20", "hasta": "2026-10-20", "proveedor": self.proveedor.pk},
            {"producto": "P-1", "proveedor": self.proveedor.pk}]:
            with self.subTest(filtro=filtro):
                respuesta = self.client.get(reverse("inventario:compras"), filtro)
                self.assertEqual(list(respuesta.context["pagina"]), [compra])
        respuesta = self.client.get(reverse("inventario:compras"), {"desde": "2026-11-01", "hasta": "2026-01-01"})
        self.assertContains(respuesta, "La fecha desde")
        self.assertEqual(len(respuesta.context["pagina"]), 0)

    def test_paginacion_y_filtro(self):
        for i in range(26): self.compra(factura=f"FACT-{i:03}")
        respuesta = self.client.get(reverse("inventario:compras"), {"factura": "FACT", "page": 2})
        self.assertEqual(len(respuesta.context["pagina"]), 1)
        self.assertContains(respuesta, "factura=FACT")
        self.assertContains(respuesta, "Página 2 de 2")

    def test_regresar_seguro(self):
        respuesta = self.client.get(reverse("inventario:nueva_compra"), {"next": "//sitio-ajeno.com"})
        self.assertEqual(respuesta.context["regresar"], reverse("inventario:compras"))
        ruta = "/inventario/?factura=F-1&page=2"
        respuesta = self.client.get(reverse("inventario:nuevo_producto"), {"next": ruta})
        self.assertEqual(respuesta.context["regresar"], ruta)
        datos = {"codigo_producto": "N-1", "nombre_producto": "Nuevo", "volumen": "100", "unidad_medida": self.unidad.pk, "activo": "on", "next": ruta}
        respuesta = self.client.post(reverse("inventario:nuevo_producto"), datos)
        self.assertRedirects(respuesta, ruta)

    def test_maestros_normalizacion_y_duplicados(self):
        self.assertFalse(ProductoForm({"codigo_producto": " p-1 ", "nombre_producto": "Repetido"}).is_valid())
        self.assertFalse(ProveedorForm({"nombre": "Otro", "rif": " j-1 "}).is_valid())
        respuesta = self.client.get(reverse("inventario:proveedores"))
        self.assertContains(respuesta, "Proveedores de inventario")

    def test_pantallas(self):
        compra = self.compra()
        rutas = ["compras", "productos", "proveedores", "nueva_compra", "nuevo_producto", "nuevo_proveedor"]
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse("inventario:" + ruta)).status_code, 200)
        for ruta in ["detalle", "editar_compra", "eliminar"]:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse("inventario:" + ruta, args=[compra.pk])).status_code, 200)

    def test_autenticacion_y_csrf(self):
        cliente = Client()
        self.assertEqual(cliente.get(reverse("inventario:compras")).status_code, 302)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(reverse("inventario:nueva_compra"), self.datos()).status_code, 403)

    def test_filtro_codigo_muestra_todos_los_detalles(self):
        compra = self.compra()
        DetalleCompra.objects.create(compra=compra, producto=self.otro_producto, cantidad=1, precio_unitario=1)
        respuesta = self.client.get(reverse("inventario:compras"), {"producto": "P-1"})
        self.assertContains(respuesta, "P-2")
        self.assertEqual(len(respuesta.context["pagina"]), 1)

    def test_formset_no_puede_usar_detalle_de_otra_compra(self):
        compra = self.compra()
        otra = self.compra(factura="OTRA")
        datos = self.datos(compra, **{"detalles-0-id": otra.detalles.get().pk})
        self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), datos)
        self.assertEqual(otra.detalles.get().cantidad, Decimal("3"))
        self.assertEqual(compra.detalles.count(), 1)

    def test_limite_detalles(self):
        datos = self.datos(**{"detalles-TOTAL_FORMS": "101"})
        form = CompraForm(datos)
        self.assertTrue(form.is_valid(), form.errors)
        detalles = DetalleFormSet(datos, instance=form.instance, prefix="detalles")
        self.assertFalse(detalles.is_valid())
        self.assertTrue(detalles.non_form_errors())

    def test_rechaza_total_convertido_desbordado(self):
        respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos(**{
            "detalles-0-cantidad": "99999999999.99", "detalles-0-precio_unitario": "99999999999999.99",
            "tasa_cambio": "999999999999.999999"}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Compra.objects.exists())
        self.assertContains(respuesta, "20 dígitos")

    def test_redondeo_comercial(self):
        compra = self.compra()
        detalle = compra.detalles.get()
        detalle.cantidad = Decimal("1")
        detalle.precio_unitario = Decimal("0.025")
        detalle.tasa_impuesto = Decimal("50")
        detalle.save()
        self.assertEqual(detalle.subtotal, Decimal("0.03"))
        self.assertEqual(detalle.monto_impuesto, Decimal("0.02"))
        self.assertEqual(detalle.total, Decimal("0.05"))

    def test_editar_quitar_agregar_sin_modificar_otra_compra(self):
        compra = self.compra()
        datos = self.datos(compra, **{"detalles-0-DELETE": "on", "detalles-TOTAL_FORMS": "2",
            "detalles-1-producto": self.otro_producto.pk, "detalles-1-cantidad": "2",
            "detalles-1-precio_unitario": "5", "detalles-1-tasa_impuesto": "0"})
        respuesta = self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(compra.detalles.get().producto, self.otro_producto)

    def test_preserva_datos_y_protecciones_de_otras_apps(self):
        from clientes.models import Cliente
        cliente = Cliente.objects.create(nombre="Cliente", apellido="Prueba", telefono="04121234567")
        with connection.cursor() as cursor:
            if connection.vendor=="mysql":
                cursor.execute("SELECT trigger_name,action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND LEFT(trigger_name,4)<>'inv_' ORDER BY trigger_name")
            else:
                cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name NOT LIKE 'inv_%' ORDER BY name")
            antes = cursor.fetchall()
        compra = self.compra()
        actualizar_compra(compra.pk, "inventario", 0)
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono, "04121234567")
        with connection.cursor() as cursor:
            if connection.vendor=="mysql":
                cursor.execute("SELECT trigger_name,action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND LEFT(trigger_name,4)<>'inv_' ORDER BY trigger_name")
            else:
                cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name NOT LIKE 'inv_%' ORDER BY name")
            self.assertEqual(cursor.fetchall(), antes)
            if connection.vendor=="mysql":
                cursor.execute("SELECT @@foreign_key_checks")
                self.assertEqual(cursor.fetchone()[0],1)
            else:
                cursor.execute("PRAGMA foreign_key_check")
                self.assertEqual(cursor.fetchall(), [])

    def test_unidades_iniciales_y_nueva_unidad(self):
        self.assertEqual(set(UnidadMedida.objects.values_list("codigo", flat=True)), {"GR", "LT", "KG", "ML"})
        respuesta = self.client.post(reverse("inventario:nueva_unidad"),
                 {"codigo": " oz ", "nombre": "onzas", "activo": "on"})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(UnidadMedida.objects.get(codigo="OZ").nombre, "ONZAS")
        self.assertEqual(self.client.get(reverse("inventario:unidades")).status_code, 200)

    def test_producto_volumen_unidad_y_mayusculas(self):
        datos = {"codigo_producto": " champ-250 ", "nombre_producto": "Champú cítrico",
                 "volumen": "250", "unidad_medida": UnidadMedida.objects.get(codigo="ML").pk,
                 "observacion": "para cabello seco", "activo": "on"}
        respuesta = self.client.post(reverse("inventario:nuevo_producto"), datos)
        self.assertEqual(respuesta.status_code, 302)
        producto = Producto.objects.get(codigo_producto="CHAMP-250")
        self.assertEqual(producto.nombre_producto, "CHAMPÚ CÍTRICO")
        self.assertEqual(producto.observacion, "PARA CABELLO SECO")
        self.assertEqual(str(producto), "CHAMP-250 · CHAMPÚ CÍTRICO · 250.00 ML")
        self.assertNotIn("modelo", ProductoForm().fields)
        self.assertContains(self.client.get(reverse("inventario:productos")), "250")
        self.assertContains(self.client.get(reverse("inventario:nuevo_producto")), "Consulta de productos")

    def test_producto_volumen_requerido_y_valido(self):
        for valor in ["", "0", "-1", "0.0001"]:
            with self.subTest(valor=valor):
                form = ProductoForm({"codigo_producto": "N", "nombre_producto": "Nombre",
                                     "volumen": valor, "unidad_medida": self.unidad.pk})
                self.assertFalse(form.is_valid())
                self.assertIn("volumen", form.errors)
        self.assertFalse(ProductoForm({"codigo_producto": "N", "nombre_producto": "Nombre", "volumen": 5}).is_valid())

    def test_unidad_inactiva(self):
        unidad = UnidadMedida.objects.create(codigo="OZ", nombre="ONZAS", activo=False)
        datos = {"codigo_producto": "N", "nombre_producto": "N", "volumen": 5, "unidad_medida": unidad.pk}
        self.assertFalse(ProductoForm(datos).is_valid())
        producto = Producto.objects.create(codigo_producto="N", nombre_producto="N", volumen=5, unidad_medida=unidad)
        self.assertTrue(ProductoForm(datos, instance=producto).is_valid())

    def test_mayusculas_proveedor_y_compra(self):
        respuesta = self.client.post(reverse("inventario:nuevo_proveedor"),
            {"nombre": "distribuidora", "rif": "j-55", "direccion": "calle uno", "activo": "on"})
        self.assertEqual(respuesta.status_code, 302)
        proveedor = Proveedor.objects.get(rif="J-55")
        self.assertEqual((proveedor.nombre, proveedor.direccion), ("DISTRIBUIDORA", "CALLE UNO"))
        self.client.post(reverse("inventario:nueva_compra"), self.datos(numero_control="ctrl-a", observacion="nota de compra"))
        compra = Compra.objects.get()
        self.assertEqual((compra.numero_control, compra.observacion), ("CTRL-A", "NOTA DE COMPRA"))

    def test_buscador_codigo_nombre_volumen_y_unidad(self):
        self.producto.volumen = Decimal("250")
        self.producto.unidad_medida = UnidadMedida.objects.get(codigo="ML")
        self.producto.save()
        for texto in ["p-1", "champú"]:
            with self.subTest(texto=texto):
                respuesta = self.client.get(reverse("inventario:buscar_productos"), {"q": texto})
                resultados = respuesta.json()["resultados"]
                self.assertEqual(len(resultados), 1)
                self.assertEqual(resultados[0]["id"], self.producto.pk)
                self.assertIn("250.00 ML", resultados[0]["texto"])
        self.assertEqual(self.client.get(reverse("inventario:buscar_productos"), {"q": ""}).json()["resultados"], [])

    def test_buscador_limite_y_activos(self):
        Producto.objects.bulk_create([Producto(codigo_producto=f"BUS-{i:03}", nombre_producto="BUSQUEDA") for i in range(25)])
        Producto.objects.create(codigo_producto="BUS-INACTIVO", nombre_producto="BUSQUEDA", activo=False)
        respuesta = self.client.get(reverse("inventario:buscar_productos"), {"q": "BUS"})
        self.assertEqual(len(respuesta.json()["resultados"]), 20)
        self.assertTrue(respuesta.json()["hay_mas"])
        respuesta = self.client.get(reverse("inventario:buscar_productos"), {"q": "BUS-INACTIVO"})
        self.assertEqual(respuesta.json()["resultados"], [])
        self.assertEqual(self.client.post(reverse("inventario:buscar_productos")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("inventario:buscar_productos"), {"q": "BUS"}).status_code, 302)

    def test_editor_no_carga_lista_completa_y_oculta_impuestos(self):
        Producto.objects.create(codigo_producto="NO-CARGAR", nombre_producto="PRODUCTO QUE NO DEBE CARGARSE")
        respuesta = self.client.get(reverse("inventario:nueva_compra"))
        self.assertNotContains(respuesta, "PRODUCTO QUE NO DEBE CARGARSE")
        self.assertNotContains(respuesta, 'name="tasa_cambio"')
        self.assertNotContains(respuesta, 'name="detalles-0-tasa_impuesto"')
        self.assertNotContains(respuesta, 'select name="detalles-0-producto"')
        self.assertContains(respuesta, "Precio Unitario")
        self.assertNotContains(respuesta, "Total estimado")
        self.assertContains(respuesta, "Consulta de productos")

    def test_bcv_automatico_por_fecha_e_ignora_post(self):
        from tasas_bcv.models import TasaBCV
        TasaBCV.objects.create(fecha=date(2026, 10, 21), tasa_bcv=45)
        respuesta = self.client.post(reverse("inventario:nueva_compra"),
                                    self.datos(fecha_compra="2026-10-21", tasa_cambio="1"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Compra.objects.get().tasa_cambio, Decimal("45"))

    def test_bcv_faltante_impide_guardar(self):
        respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos(fecha_compra="2020-01-01"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No hay tasa BCV")
        self.assertFalse(Compra.objects.exists())
        self.assertEqual(self.client.get(reverse("inventario:condiciones"), {"fecha": "2020-01-01"}).status_code, 422)
        self.assertEqual(self.client.get(reverse("inventario:condiciones"), {"fecha": "no-fecha"}).status_code, 400)

    def test_iva_automatico_ignora_post(self):
        from unittest.mock import patch
        with patch("inventario.condiciones.leer_impuesto", return_value=Decimal("8.00")):
            respuesta = self.client.post(reverse("inventario:nueva_compra"),
                                        self.datos(**{"detalles-0-tasa_impuesto": "99"}))
        self.assertEqual(respuesta.status_code, 302)
        compra = Compra.objects.get()
        self.assertEqual(compra.detalles.get().tasa_impuesto, Decimal("8"))
        self.assertEqual(compra.total, Decimal("32.40"))

    def test_condiciones_devuelve_bcv_e_iva_del_sistema(self):
        respuesta = self.client.get(reverse("inventario:condiciones"), {"fecha": "2026-10-20"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Decimal(respuesta.json()["tasa"]), Decimal("40"))
        self.assertEqual(Decimal(respuesta.json()["iva"]), Decimal("16"))

    def test_configuracion_iva_invalida_no_guarda(self):
        from unittest.mock import patch
        with patch("inventario.condiciones.leer_impuesto", side_effect=ValueError("JSON inválido")):
            respuesta = self.client.post(reverse("inventario:nueva_compra"), self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No se pudo leer el IVA")
        self.assertFalse(Compra.objects.exists())

    def test_actualizar_conserva_importes_revisados_aunque_cambie_configuracion(self):
        from tasas_bcv.models import TasaBCV
        from unittest.mock import patch
        compra = self.compra()
        TasaBCV.objects.filter(fecha=compra.fecha_compra).update(tasa_bcv=80)
        with patch("inventario.condiciones.leer_impuesto", return_value=Decimal("8")):
            actualizar_compra(compra.pk, "inventario", 0)
        compra.refresh_from_db()
        self.assertEqual(compra.tasa_cambio, Decimal("40"))
        self.assertEqual(compra.detalles.get().tasa_impuesto, Decimal("16"))
        self.assertEqual(compra.total, Decimal("34.80"))

    def test_editar_borrador_actualiza_iva_en_fila_sin_cambios(self):
        from unittest.mock import patch
        compra = self.compra(factura="FACT-1")
        with patch("inventario.condiciones.leer_impuesto", return_value=Decimal("8")):
            respuesta = self.client.post(reverse("inventario:editar_compra", args=[compra.pk]), self.datos(compra))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(compra.detalles.get().tasa_impuesto, Decimal("8"))

    def test_consulta_no_muestra_columna_impuesto(self):
        compra = self.compra()
        respuesta = self.client.get(reverse("inventario:detalle", args=[compra.pk]))
        self.assertNotContains(respuesta, "<th>Impuesto")
        self.assertNotContains(respuesta, "<th>Monto impuesto")
        self.assertContains(respuesta, '<th class="text-end">Volumen</th>')
        self.assertContains(respuesta, "<th>Unidad</th>")
