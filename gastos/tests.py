from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.db import IntegrityError,transaction
from django.db.models.deletion import ProtectedError
from .models import GrupoGasto,TipoGasto,Proveedor,RegistroGasto
from .forms import RegistroForm,ProveedorForm


class GastosTests(TestCase):
    def setUp(self):
        self.grupo=GrupoGasto.objects.create(descripcion="Operación")
        self.tipo=TipoGasto.objects.create(descripcion="Insumos",grupo=self.grupo)
        self.proveedor=Proveedor.objects.create(rif="J-12345678-9",descripcion="Proveedor de prueba")

    def datos(self,**cambios):
        datos={"fecha_gasto":"2026-10-17","gasto":self.tipo.pk,"proveedor":self.proveedor.pk,"numero_factura":"F-1","numero_control":"C-1","moneda":"USD","monto_gasto":"100.00","monto_impuesto":"7.00","porcentaje_impuesto":"25.00"}
        datos.update(cambios);return datos

    def guardar(self,**cambios):
        form=RegistroForm(self.datos(**cambios))
        self.assertTrue(form.is_valid(),form.errors)
        return form.save()

    def test_impuesto_manual_no_se_recalcula(self):
        objeto=self.guardar()
        self.assertEqual(objeto.monto_impuesto,Decimal("7.00"))
        self.assertEqual(objeto.total,Decimal("107.00"))

    def test_editar_y_eliminar(self):
        objeto=self.guardar()
        form=RegistroForm(self.datos(monto_gasto="200.00",monto_impuesto="9.00"),instance=objeto)
        self.assertTrue(form.is_valid(),form.errors)
        actualizado=form.save()
        self.assertEqual(actualizado.total,Decimal("209.00"))
        actualizado.delete()
        self.assertFalse(RegistroGasto.objects.exists())

    def test_factura_duplicada_y_otro_proveedor(self):
        self.guardar()
        form=RegistroForm(self.datos(numero_factura=" f-1 "))
        self.assertFalse(form.is_valid())
        proveedor2=Proveedor.objects.create(rif="J-22222222-2",descripcion="Otro")
        self.guardar(proveedor=proveedor2.pk)
        self.assertEqual(RegistroGasto.objects.count(),2)

    def test_registros_usados_protegidos(self):
        self.guardar()
        for objeto in [self.tipo,self.proveedor,self.grupo]:
            with self.subTest(objeto=objeto),self.assertRaises(ProtectedError):objeto.delete()

    def test_activos_al_crear_e_inactivos_al_editar(self):
        objeto=self.guardar()
        Proveedor.objects.filter(pk=self.proveedor.pk).update(activo=False)
        GrupoGasto.objects.filter(pk=self.grupo.pk).update(activo=False)
        nuevo=RegistroForm(self.datos(numero_factura="F-2"))
        self.assertFalse(nuevo.is_valid())
        existente=RegistroForm(self.datos(monto_impuesto="8.00"),instance=objeto)
        self.assertTrue(existente.is_valid(),existente.errors)

    def test_moneda_importes_y_porcentaje(self):
        for cambio in [{"moneda":"EUR"},{"monto_gasto":"0"},{"monto_impuesto":"-1"},{"porcentaje_impuesto":"101"},{"monto_gasto":"1.001"}]:
            with self.subTest(cambio=cambio):self.assertFalse(RegistroForm(self.datos(**cambio)).is_valid())

    def test_normalizacion_rif(self):
        form=ProveedorForm({"rif":" j-12345678-9 ","descripcion":"Duplicado","activo":True})
        self.assertFalse(form.is_valid())


from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Producto, DetalleRegistroGasto
from .forms import DetalleGastoFormSet


class ProductosGastoTests(GastosTests):
    def setUp(self):
        super().setUp()
        self.producto=Producto.objects.create(descripcion='Champú')
        self.client.force_login(get_user_model().objects.create_user(username='prueba',password='clave-prueba'))

    def lineas(self, cantidad='2.500', producto=None):
        return {'detalles-TOTAL_FORMS':'1','detalles-INITIAL_FORMS':'0',
                'detalles-MIN_NUM_FORMS':'0','detalles-MAX_NUM_FORMS':'100',
                'detalles-0-producto':str(producto or self.producto.pk),
                'detalles-0-cantidad':cantidad}

    def test_guarda_encabezado_y_detalle_sin_cambiar_importes(self):
        response=self.client.post(reverse('gastos:crear'),{**self.datos(),**self.lineas()})
        self.assertEqual(response.status_code,302)
        objeto=RegistroGasto.objects.get()
        self.assertEqual(objeto.total,Decimal('107.00'))
        self.assertEqual(objeto.detalles.get().cantidad,Decimal('2.500'))

    def test_detalle_invalido_no_guarda_encabezado(self):
        # Avoid rendering the real project's base template in this isolated suite.
        from unittest.mock import patch
        from django.http import HttpResponse
        for cantidad in ['0','-1','1.0001']:
            with self.subTest(cantidad=cantidad),patch('gastos.views.render',return_value=HttpResponse('formulario')):
                self.client.post(reverse('gastos:crear'),{**self.datos(),**self.lineas(cantidad)})
                self.assertFalse(RegistroGasto.objects.exists())

    def test_inactivo_no_se_asigna_pero_se_conserva_en_edicion(self):
        gasto=self.guardar()
        linea=DetalleRegistroGasto.objects.create(registro_gasto=gasto,producto=self.producto,cantidad=2)
        self.producto.activo=False;self.producto.save()
        nuevo=DetalleGastoFormSet(self.lineas(),instance=RegistroGasto(),prefix='detalles')
        self.assertFalse(nuevo.is_valid())
        datos=self.lineas();datos.update({'detalles-INITIAL_FORMS':'1','detalles-0-id_detalle_registro':str(linea.pk)})
        editar=DetalleGastoFormSet(datos,instance=gasto,prefix='detalles')
        self.assertTrue(editar.is_valid(),editar.errors)

    def test_producto_usado_protegido_y_gasto_elimina_su_detalle(self):
        gasto=self.guardar()
        DetalleRegistroGasto.objects.create(registro_gasto=gasto,producto=self.producto,cantidad=1)
        with self.assertRaises(ProtectedError):self.producto.delete()
        gasto.delete()
        self.assertFalse(DetalleRegistroGasto.objects.exists())
        self.assertTrue(Producto.objects.filter(pk=self.producto.pk).exists())

    def test_editar_agregar_quitar_lineas(self):
        gasto=self.guardar()
        linea=DetalleRegistroGasto.objects.create(registro_gasto=gasto,producto=self.producto,cantidad=1)
        datos=self.lineas();datos.update({'detalles-INITIAL_FORMS':'1','detalles-0-id_detalle_registro':str(linea.pk),'detalles-0-DELETE':'on'})
        response=self.client.post(reverse('gastos:editar',args=[gasto.pk]),{**self.datos(),**datos})
        self.assertEqual(response.status_code,302)
        self.assertFalse(gasto.detalles.exists())

    def test_sin_productos_admite_gastos_generales(self):
        datos={'detalles-TOTAL_FORMS':'0','detalles-INITIAL_FORMS':'0'}
        self.assertTrue(DetalleGastoFormSet(datos,instance=RegistroGasto(),prefix='detalles').is_valid())
