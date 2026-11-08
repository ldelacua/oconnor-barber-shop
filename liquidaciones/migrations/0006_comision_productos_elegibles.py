from importlib import import_module
from django.db import migrations

ELEGIBLES = "FROM ventas_productos_lineaproducto x WHERE x.documento_id=v.id AND x.sin_comision=0"
EXISTE = "AND EXISTS(SELECT 1 " + ELEGIBLES + ") "
CAMBIOS = {
    "lcp_periodo_insert": [("NEW.base_usd*NEW.porcentaje/100,2", "NEW.base_usd*NEW.porcentaje/100.0,2")],
    "lcp_venta_insert": [
        ("NEW.unidades=v.unidades_total", "ABS(NEW.unidades-(SELECT COALESCE(SUM(x.cantidad),0) " + ELEGIBLES + "))<0.005"),
        ("NEW.base_usd-(v.subtotal_usd-v.descuento_usd)", "NEW.base_usd-(SELECT COALESCE(SUM(x.subtotal_usd-x.descuento_usd),0) " + ELEGIBLES + ")"),
    ],
    "liq_sellar": [
        ("*p.porcentaje/100,2", "*p.porcentaje/100.0,2"),
        ("AND NOT EXISTS(SELECT 1 FROM liquidaciones_comisionventaproducto c WHERE c.periodo_id=p.id AND c.venta_id=v.id)",
         EXISTE + "AND NOT EXISTS(SELECT 1 FROM liquidaciones_comisionventaproducto c WHERE c.periodo_id=p.id AND c.venta_id=v.id)"),
    ],
}


def instalar(apps, editor):
    import_module("ventas.migrations.0016_detalleventa_propina_bs").cambiar_reglas(editor, CAMBIOS)


def retirar(apps, editor):
    import_module("ventas.migrations.0016_detalleventa_propina_bs").cambiar_reglas(
        editor, {k: [(b, a) for a, b in reversed(v)] for k, v in CAMBIOS.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("liquidaciones", "0005_liquidacion_total_propinas_bs"),
        ("ventas_productos", "0008_lineaproducto_sin_comision"),
    ]
    operations = [migrations.RunPython(instalar, retirar)]
