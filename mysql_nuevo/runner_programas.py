"""Suite experimental: informa las pruebas que dependen de SQL directo."""
import unittest
from django.test.runner import DiscoverRunner

PRUEBAS_SQL_DIRECTO = frozenset({
    'inventario.test_pagos_proveedor.PagosProveedorTests.test_sql_no_modifica_pago_registrado',
    'control_inventario.tests.ControlInventarioTests.test_documento_y_detalle_inmutables_sql',
    'inventario.tests.InventarioTests.test_bloqueo_sql_cabecera_y_detalle_y_movimiento',
    'ventas.test_descuentos.DescuentosTests.test_factura_y_pago_guardados_siguen_inmutables',
    'ventas.test_descuentos.DescuentosTests.test_sellado_no_permite_cambiar_descuento',
    'ventas.test_iva_incluido.VentaIvaIncluidoTests.test_sql_bloquea_cambiar_modo_y_bases_de_documento_sellado',
    'ventas_productos.tests.VentaProductosTests.test_bloqueo_sql_documento_detalle_pago',
    'ventas_productos.test_prestador_venta.PrestadorVentaTests.test_proteccion_sql_impide_alterar_comision_liquidada',
    'mysql_nuevo.test_integracion.IntegracionMysqlTests.test_disparadores_y_vista_instalados',
})

class ProteccionSqlNoDisponible(unittest.TestCase):
    def __init__(self, nombre):
        super().__init__()
        self.nombre = nombre
    def id(self):
        return self.nombre
    def __str__(self):
        return self.nombre
    def runTest(self):
        self.skipTest('Requiere disparadores: SQL directo no está protegido en el experimento.')

class RunnerProgramas(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        original = super().build_suite(*args, **kwargs)
        encontrados = set()
        def adaptar(suite):
            nuevo = unittest.TestSuite()
            for prueba in suite:
                if isinstance(prueba, unittest.TestSuite):
                    nuevo.addTest(adaptar(prueba))
                elif prueba.id() in PRUEBAS_SQL_DIRECTO:
                    encontrados.add(prueba.id())
                    nuevo.addTest(ProteccionSqlNoDisponible(prueba.id()))
                else:
                    nuevo.addTest(prueba)
            return nuevo
        resultado = adaptar(original)
        if encontrados != PRUEBAS_SQL_DIRECTO:
            faltan = sorted(PRUEBAS_SQL_DIRECTO - encontrados)
            raise RuntimeError('No se encontró la suite completa esperada: ' + ', '.join(faltan))
        print(f'Se informarán {len(PRUEBAS_SQL_DIRECTO)} pruebas omitidas: dependen de disparadores o de protección SQL directa.', flush=True)
        return resultado
