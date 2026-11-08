from django.db import migrations, models


def cambiar_reglas(editor, cambios):
    for nombre, pares in cambios.items():
        with editor.connection.cursor() as cursor:
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=%s", [nombre])
            sql = cursor.fetchone()[0]
        for anterior, nuevo in pares:
            if anterior not in sql:
                raise RuntimeError(f"No se encontró la regla esperada de {nombre}.")
            sql = sql.replace(anterior, nuevo)
        editor.execute(f"DROP TRIGGER {nombre}")
        editor.execute(sql)


CAMBIOS = {
    "ventas_doc_sellar": [
        ("NEW.total_bs - NEW.subtotal_bs - NEW.total_impuesto_bs",
         "NEW.total_bs - NEW.subtotal_bs - NEW.total_impuesto_bs - (SELECT COALESCE(SUM(propina_bs),0) FROM ventas_detalleventa WHERE id_documento=NEW.id_documento)"),
    ],
    "ventas_detalle_validar": [
        ("NEW.linea_original_id IS NULL", "NEW.linea_original_id IS NULL AND NEW.propina_bs>=0"),
        ("AND NEW.promocion=o.promocion", "AND NEW.propina_bs=-o.propina_bs AND NEW.promocion=o.promocion"),
    ],
}


def instalar(apps, editor):
    cambiar_reglas(editor, CAMBIOS)


def retirar(apps, editor):
    cambiar_reglas(editor, {nombre: [(b, a) for a, b in reversed(pares)] for nombre, pares in CAMBIOS.items()})


class Migration(migrations.Migration):
    dependencies = [("ventas", "0015_detalleventa_propina_usd")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                "ALTER TABLE ventas_detalleventa ADD COLUMN propina_bs decimal NOT NULL DEFAULT 0",
                "ALTER TABLE ventas_detalleventa DROP COLUMN propina_bs",
            )],
            state_operations=[migrations.AddField("detalleventa", "propina_bs",
                                                 models.DecimalField(max_digits=14, decimal_places=2, default=0))],
        ),
        migrations.RunPython(instalar, retirar),
    ]
