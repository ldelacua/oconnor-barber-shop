from importlib import import_module
from django.db import migrations, models


def anteriores():
    return import_module("ventas.migrations.0002_proteger_documentos")


def retirar_anteriores(apps, schema_editor):
    anteriores().retirar(apps, schema_editor)


def instalar_anteriores(apps, schema_editor):
    anteriores().instalar(apps, schema_editor)


def sentencias_nuevas():
    sql = list(anteriores().SQL)
    for indice, sentencia in enumerate(sql):
        if "CREATE TRIGGER ventas_detalle_validar " in sentencia:
            sql[indice] = sentencia.replace(
                "WHEN NEW.cantidad_servicio <= 0",
                """WHEN NEW.cantidad_servicio <= 0
OR (NEW.barbero_id IS NULL AND EXISTS(
    SELECT 1 FROM ventas_documentoventa d
    WHERE d.id_documento = NEW.id_documento AND d.tipo_documento = 'FA'
))
OR (NEW.descripcion_barbero = '' AND EXISTS(
    SELECT 1 FROM ventas_documentoventa d
    WHERE d.id_documento = NEW.id_documento AND d.tipo_documento = 'FA'
))""",
            )
    return sql


def instalar_nuevos(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        raise RuntimeError("Esta protección de Ventas requiere SQLite.")
    for sentencia in sentencias_nuevas():
        schema_editor.execute(sentencia)


def retirar_nuevos(apps, schema_editor):
    anteriores().retirar(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0002_proteger_documentos"),
        ("barberos", "__first__"),
    ]
    operations = [
        migrations.RunPython(retirar_anteriores, instalar_anteriores),
        migrations.AddField(
            model_name="detalleventa",
            name="barbero",
            field=models.ForeignKey(
                to="barberos.barbero", null=True, blank=True,
                on_delete=models.PROTECT, related_name="detalles_venta",
            ),
        ),
        migrations.AddField(
            model_name="detalleventa",
            name="descripcion_barbero",
            field=models.CharField(max_length=220, blank=True, default=""),
        ),
        migrations.RunPython(instalar_nuevos, retirar_nuevos),
    ]
