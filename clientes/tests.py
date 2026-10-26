from datetime import date
from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import get_template
from .forms import ClienteForm
from .models import Cliente

class ClientesTests(TestCase):
    def datos(self, **cambios):
        datos = dict(nombre="María", apellido="Pérez", telefono="0123456789",
                     email="Cliente@example.com", direccion="Calle uno",
                     observaciones="Nota", dia_nacimiento="29", mes_nacimiento="2")
        datos.update(cambios)
        return datos

    def test_mayusculas_y_cero_inicial(self):
        form = ClienteForm(self.datos())
        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono, "0123456789")
        self.assertEqual(cliente.nombre, "MARÍA")
        self.assertEqual(cliente.apellido, "PÉREZ")
        self.assertEqual(cliente.email, "CLIENTE@EXAMPLE.COM")
        self.assertEqual(cliente.direccion, "CALLE UNO")
        self.assertEqual(cliente.observaciones, "NOTA")
        self.assertIsNone(cliente.fecha_nacimiento)

    def test_telefonos_invalidos(self):
        for telefono in ["123", "12345678901", "12345abcde", "123-456789", "１２３４５６７８９０"]:
            with self.subTest(telefono=telefono):
                form = ClienteForm(self.datos(telefono=telefono))
                self.assertFalse(form.is_valid())
                self.assertIn("telefono", form.errors)

    def test_fechas_invalidas(self):
        for dia, mes in [("31", "4"), ("30", "2"), ("1", ""), ("", "3"), ("0", "1"), ("1", "13")]:
            with self.subTest(dia=dia, mes=mes):
                self.assertFalse(ClienteForm(self.datos(dia_nacimiento=dia, mes_nacimiento=mes)).is_valid())

    def test_nacimiento_opcional(self):
        form = ClienteForm(self.datos(dia_nacimiento="", mes_nacimiento=""))
        self.assertTrue(form.is_valid(), form.errors)

    def test_edicion(self):
        cliente = Cliente.objects.create(nombre="uno", apellido="dos", telefono="123",
                                         dia_nacimiento=3, mes_nacimiento=5)
        self.assertEqual(ClienteForm(instance=cliente).initial["dia_nacimiento"], 3)
        form = ClienteForm(self.datos(telefono="123"), instance=cliente)
        self.assertFalse(form.is_valid())
        form = ClienteForm(self.datos(), instance=cliente)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().pk, cliente.pk)

    def test_modelo_y_plantillas(self):
        cliente = Cliente(nombre="uno", apellido="dos", telefono="0123456789",
                          dia_nacimiento=29, mes_nacimiento=2)
        cliente.full_clean()
        self.assertEqual(cliente.nombre, "UNO")
        for nombre in ["formulario", "detalle", "editar", "lista"]:
            get_template("clientes/" + nombre + ".html")
        self.assertNotIn("fecha_nacimiento", ClienteForm().fields)

class MigracionTests(TransactionTestCase):
    def test_datos_anteriores_y_trigger(self):
        anterior = ("clientes", "0002_remove_cliente_codigo_remove_cliente_correo_and_more")
        actual = ("clientes", "0003_dia_mes_mayusculas")
        executor = MigrationExecutor(connection)
        executor.migrate([anterior])
        ClienteAnterior = executor.loader.project_state([anterior]).apps.get_model("clientes", "Cliente")
        cliente = ClienteAnterior.objects.create(nombre="José", apellido="Díaz", telefono="123",
                                                email="a@example.com", fecha_nacimiento=date(1980, 2, 29))
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE referencia (cliente_id INTEGER REFERENCES clientes_cliente(id))")
            cursor.execute("CREATE TRIGGER comprobar_cliente BEFORE INSERT ON referencia BEGIN SELECT id FROM clientes_cliente WHERE id = NEW.cliente_id; END")
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([actual])
            actualizado = Cliente.objects.get(pk=cliente.pk)
            self.assertEqual((actualizado.dia_nacimiento, actualizado.mes_nacimiento), (29, 2))
            self.assertEqual(actualizado.nombre, "JOSÉ")
            self.assertEqual(actualizado.telefono, "123")
            self.assertEqual(actualizado.fecha_nacimiento, date(1980, 2, 29))
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO referencia (cliente_id) VALUES (%s)", [cliente.pk])
                cursor.execute("PRAGMA foreign_key_check")
                self.assertEqual(cursor.fetchall(), [])
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TRIGGER IF EXISTS comprobar_cliente")
                cursor.execute("DROP TABLE IF EXISTS referencia")
