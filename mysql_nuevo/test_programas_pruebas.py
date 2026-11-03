"""Comprobaciones limitadas del esquema experimental sin disparadores."""
from unittest import skipUnless
from django.db import connection
from django.test import TestCase

@skipUnless(connection.vendor == 'mysql', 'Requiere MySQL real.')
class EsquemaExperimentalTests(TestCase):
    def test_instala_vista_candado_y_no_disparadores(self):
        with connection.cursor() as c:
            c.execute('SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()')
            self.assertEqual(c.fetchone()[0], 0)
            c.execute("SELECT security_type FROM information_schema.views WHERE table_schema=DATABASE() AND table_name='ci_movimientos'")
            self.assertEqual(c.fetchone()[0], 'INVOKER')
            c.execute('SELECT id FROM mysql_candado_operaciones WHERE id=1')
            self.assertEqual(c.fetchone()[0], 1)

from importlib import import_module
from unittest.mock import MagicMock
from django.test import SimpleTestCase


class MigracionComisionesTests(SimpleTestCase):
    def test_sin_disparadores_no_intenta_instalarlos(self):
        migracion = import_module('mysql_nuevo.esquema.liquidaciones.0003_protecciones_comision')
        editor = MagicMock()
        editor.connection.vendor = 'mysql'
        editor.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        migracion.instalar(None, editor)
        editor.execute.assert_not_called()

    def test_con_protecciones_incompletas_no_modifica_disparadores(self):
        migracion = import_module('mysql_nuevo.esquema.liquidaciones.0003_protecciones_comision')
        editor = MagicMock()
        editor.connection.vendor = 'mysql'
        editor.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [('uno',)]
        with self.assertRaises(RuntimeError):
            migracion.instalar(None, editor)
        editor.execute.assert_not_called()

    def test_definiciones_nuevas_incluyen_las_protecciones_de_comision(self):
        from mysql_nuevo.protecciones_comisiones import sentencias
        reglas = sentencias()
        self.assertEqual(len(reglas), 12)
        self.assertIn('liquidaciones_reintegrocomisionproducto', reglas['liq_sellar'])
        self.assertIn('Periodo de comisiones ya liquidado', reglas['ci_venta_periodo'])
        self.assertIn('NEW.prestador_id <=> o.prestador_id', reglas['vp_validar_sello'])

class MigracionPagosProveedorTests(SimpleTestCase):
    def test_perfil_sin_disparadores_no_intenta_crearlos(self):
        migracion = import_module('mysql_nuevo.esquema.inventario.0003_protecciones_pagos')
        editor = MagicMock()
        editor.connection.vendor = 'mysql'
        editor.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        migracion.instalar(None, editor)
        editor.execute.assert_not_called()

    def test_instalacion_incompleta_no_se_modifica(self):
        migracion = import_module('mysql_nuevo.esquema.inventario.0003_protecciones_pagos')
        editor = MagicMock()
        editor.connection.vendor = 'mysql'
        editor.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [('otro',)]
        with self.assertRaises(RuntimeError): migracion.instalar(None, editor)
        editor.execute.assert_not_called()

    def test_moneda_de_pago_y_compra_comparan_con_colacion_explicita(self):
        from mysql_nuevo.protecciones_pagos import sentencias, CONDICION
        sql = sentencias()['pp_validar']
        self.assertIn('(NEW.moneda COLLATE utf8mb4_0900_as_cs)=(c.divisa COLLATE utf8mb4_0900_as_cs)', sql)
        self.assertNotIn('NEW.moneda=c.divisa', sql)
        self.assertNotIn('COLLATE', CONDICION)
