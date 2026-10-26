"""Pruebas reales para ejecutar en MySQL 8.4; no se simula el servidor."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date,time
from decimal import Decimal as D
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import connection,transaction,IntegrityError,close_old_connections
from django.test import TransactionTestCase


@skipUnless(connection.vendor=='mysql','Se ejecuta únicamente en MySQL real.')
class IntegracionMysqlTests(TransactionTestCase):
    def _fixture_teardown(self):
        # DELETE dispara las protecciones de documentos inmutables y puede borrar
        # el candado antes que las otras tablas. TRUNCATE no ejecuta triggers.
        # Este reemplazo existe únicamente durante la limpieza de estas pruebas.
        import os
        esperado = os.environ.get('MYSQL_TEST_DATABASE', '')
        if not esperado.startswith('verificacion_barberia_'):
            raise RuntimeError('Ejecuta estas pruebas mediante pruebas_mysql.py.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            if cursor.fetchone()[0] != esperado:
                raise RuntimeError('Se rechazó limpiar una base distinta a la temporal.')

        sql_flush_original = connection.ops.sql_flush

        def sql_limpieza(style, tables, **kwargs):
            kwargs['reset_sequences'] = True
            return sql_flush_original(style, tables, **kwargs)

        try:
            with patch.object(connection.ops, 'sql_flush', side_effect=sql_limpieza):
                super()._fixture_teardown()
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SET FOREIGN_KEY_CHECKS=1')

    def setUp(self):
        from mysql_nuevo.models import CandadoOperaciones
        from clientes.models import Cliente
        from barberos.models import Barbero
        from servicios.models import Servicio
        from tasas_bcv.models import TasaBCV
        from inventario.models import Producto,Proveedor,Compra,DetalleCompra
        from inventario.services import actualizar_compra
        CandadoOperaciones.objects.get_or_create(pk=1)
        self.fecha=date(2026,10,20)
        self.usuario=SimpleNamespace(get_username=lambda:'PRUEBA MYSQL')
        self.cliente=Cliente.objects.create(nombre='PRUEBA',apellido='MYSQL',telefono='04121234567')
        self.barbero=Barbero.objects.create(codigo='MYSQL',nombre='PRESTADOR',apellido='MYSQL',direccion='PRUEBA',telefono='04121234567',fecha_ingreso=date(2026,10,1),porcentaje=50)
        self.servicio=Servicio.objects.create(codigo='MYSQL',nombre='SERVICIO MYSQL',precio=116,duracion=30,retencion_impuesto=True)
        self.producto=Producto.objects.create(codigo_producto='MYSQL',nombre_producto='PRODUCTO MYSQL')
        proveedor=Proveedor.objects.create(nombre='PROVEEDOR MYSQL',rif='J-MYSQL')
        compra=Compra.objects.create(proveedor=proveedor,numero_factura='MYSQL',fecha_compra=date(2026,10,1),tasa_cambio=40,registrada_por='PRUEBA')
        DetalleCompra.objects.create(compra=compra,producto=self.producto,cantidad=10,precio_unitario=10)
        actualizar_compra(compra.pk,'PRUEBA',0)
        from ventas_productos.models import PorcentajeProducto
        PorcentajeProducto.objects.create(producto=self.producto,porcentaje=50)
        TasaBCV.objects.create(fecha=self.fecha,tasa_bcv=40)
        self.catalogo={5:dict(id=5,nombre='EFECTIVO USD',moneda='USD')}

    def venta_producto(self,cantidad,clave):
        from ventas_productos.servicios import registrar_venta
        return registrar_venta(fecha=self.fecha,cliente=self.cliente,lineas=[dict(producto=self.producto,cantidad=cantidad)],
            pagos=[dict(tipo_pago='5',fecha=self.fecha,monto=D(cantidad)*D('17.40'))],clave=clave,usuario=self.usuario)

    def simultaneas(self,funcion):
        barrera=Barrier(2)
        def ejecutar(n):
            close_old_connections();barrera.wait(timeout=15)
            try:
                try:return funcion(n)
                except ValidationError:return 'rechazada'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros=[pool.submit(ejecutar,n) for n in [1,2]]
            return [f.result(timeout=40) for f in futuros]

    def test_dos_ventas_no_sobrevenden(self):
        from inventario.existencias import existencia_producto
        from ventas_productos.models import DocumentoProducto
        with patch('ventas_productos.servicios.leer_tipos_pago',return_value=self.catalogo),patch('ventas_productos.servicios.iva_vigente',return_value=D('16')):
            resultados=self.simultaneas(lambda n:self.venta_producto(7,uuid.uuid4()).pk)
        self.assertEqual(resultados.count('rechazada'),1)
        self.assertEqual(DocumentoProducto.objects.filter(sellado=True).count(),1)
        self.assertEqual(existencia_producto(self.producto.pk),D('3.000'))

    def test_doble_envio_no_duplica_venta(self):
        from inventario.existencias import existencia_producto
        from ventas_productos.models import DocumentoProducto
        clave=uuid.uuid4()
        with patch('ventas_productos.servicios.leer_tipos_pago',return_value=self.catalogo),patch('ventas_productos.servicios.iva_vigente',return_value=D('16')):
            resultados=self.simultaneas(lambda n:self.venta_producto(2,clave).pk)
        self.assertEqual(resultados[0],resultados[1])
        self.assertEqual(DocumentoProducto.objects.count(),1)
        self.assertEqual(existencia_producto(self.producto.pk),D('8.000'))

    def test_no_se_liquida_dos_veces_un_servicio(self):
        from ventas.servicios import registrar_venta
        from liquidaciones.servicios import registrar
        from liquidaciones.models import Liquidacion
        with patch('ventas.servicios.leer_tipos_pago',return_value=self.catalogo),patch('ventas.servicios.leer_impuesto',return_value=D('16')):
            fa=registrar_venta(fecha=self.fecha,cliente=self.cliente,usuario=self.usuario,clave=uuid.uuid4(),
              lineas=[dict(servicio=self.servicio,barbero=self.barbero,cantidad_servicio=1)],pagos=[dict(tipo_pago='5',fecha=self.fecha,monto=D('116'))])
        linea=fa.detalles.get().pk
        def pagar(n):
            return registrar(prestador_id=self.barbero.pk,desde=self.fecha,hasta=self.fecha,fecha=self.fecha,
              seleccion=[linea],pagos=[dict(tipo_pago='5',fecha=self.fecha,monto=D('58'))],clave=uuid.uuid4(),usuario=self.usuario).pk
        with patch('liquidaciones.servicios.leer_tipos_pago',return_value=self.catalogo):resultados=self.simultaneas(pagar)
        self.assertEqual(resultados.count('rechazada'),1)
        self.assertEqual(Liquidacion.objects.filter(sellado=True).count(),1)

    def test_indice_cita_activa_y_canceladas(self):
        from citas.models import Cita
        def cita(estado):return Cita(cliente=self.cliente,barbero=self.barbero,servicio=self.servicio,fecha=self.fecha,hora=time(10),estado=estado)
        Cita.objects.bulk_create([cita('cancelada'),cita('cancelada'),cita('pendiente')])
        with self.assertRaises(IntegrityError),transaction.atomic():Cita.objects.bulk_create([cita('confirmada')])
        self.assertEqual(Cita.objects.count(),3)

    def test_indice_un_solo_conteo_abierto(self):
        from control_inventario.models import CierreMensual
        CierreMensual.objects.create(periodo=date(2026,8,1),iniciado_por='PRUEBA')
        with self.assertRaises(IntegrityError),transaction.atomic():CierreMensual.objects.create(periodo=date(2026,9,1),iniciado_por='PRUEBA')
        self.assertEqual(CierreMensual.objects.count(),1)

    def test_disparadores_y_vista_instalados(self):
        from mysql_nuevo.verificacion import comprobar
        resultado=comprobar(connection)
        self.assertEqual(resultado['disparadores'],57)
