from importlib import import_module
from django.db import migrations, models

CAMBIOS = {
    "liq_no_update": [
        ("NEW.total_bs IS OLD.total_bs", "NEW.total_bs IS OLD.total_bs AND NEW.total_propinas_bs IS OLD.total_propinas_bs"),
    ],
    "liq_validar": [(" OR NEW.total_comision_usd<=0", "")],
    "liq_sellar": [
        ("ROUND(NEW.total_comision_usd*NEW.tasa_bcv,2)",
         "(ROUND(NEW.total_comision_usd*NEW.tasa_bcv,2)+NEW.total_propinas_bs)"),
        ("ABS(NEW.total_comision_usd-(SELECT COALESCE(SUM(monto),0)",
         "ABS((CASE WHEN NEW.total_propinas_bs=0 THEN NEW.total_comision_usd ELSE ROUND(NEW.total_bs/NEW.tasa_bcv,2) END)-(SELECT COALESCE(SUM(monto),0)"),
        ("WHEN NEW.sellado=1 AND (",
         "WHEN NEW.sellado=1 AND (ABS(NEW.total_propinas_bs-(SELECT COALESCE(SUM(v.propina_bs),0) FROM liquidaciones_detalleliquidacion d JOIN ventas_detalleventa v ON v.id=d.detalle_venta_id WHERE d.liquidacion_id=NEW.id_cancelacion))>0.005 OR "),
    ],
}
# Usa un reemplazo reversible incluso cuando la regla original se elimina.
CAMBIOS["liq_validar"] = [(" OR NEW.total_comision_usd<=0", " OR (NEW.total_comision_usd<=0 AND NEW.total_bs<=0)")]


def instalar(apps, editor):
    import_module("ventas.migrations.0016_detalleventa_propina_bs").cambiar_reglas(editor, CAMBIOS)


def retirar(apps, editor):
    import_module("ventas.migrations.0016_detalleventa_propina_bs").cambiar_reglas(
        editor, {nombre: [(b, a) for a, b in reversed(pares)] for nombre, pares in CAMBIOS.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("liquidaciones", "0004_protecciones_comision_productos"),
        ("ventas", "0016_detalleventa_propina_bs"),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                "ALTER TABLE liquidaciones_liquidacion ADD COLUMN total_propinas_bs decimal NOT NULL DEFAULT 0",
                "ALTER TABLE liquidaciones_liquidacion DROP COLUMN total_propinas_bs",
            )],
            state_operations=[migrations.AddField("liquidacion", "total_propinas_bs",
                                                 models.DecimalField(max_digits=18, decimal_places=2, default=0))],
        ),
        migrations.RunPython(instalar, retirar),
    ]
