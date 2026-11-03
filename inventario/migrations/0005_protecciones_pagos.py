from django.db import migrations
from mysql_nuevo.protecciones_pagos import CONDICION


def instalar(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite': return
    schema_editor.execute("CREATE TRIGGER pp_validar BEFORE INSERT ON inventario_pagoproveedor WHEN " + CONDICION.replace('NEW.monto/NEW.tasa_cambio', 'NEW.monto*1.0/NEW.tasa_cambio') + " BEGIN SELECT RAISE(ABORT,'Pago a proveedor inválido o excede saldo'); END")
    for evento in ('UPDATE', 'DELETE'):
        schema_editor.execute(f"CREATE TRIGGER pp_no_{evento.lower()} BEFORE {evento} ON inventario_pagoproveedor BEGIN SELECT RAISE(ABORT,'Pago a proveedor inmutable'); END")

def retirar(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite': return
    for nombre in ('pp_validar', 'pp_no_update', 'pp_no_delete'):
        schema_editor.execute('DROP TRIGGER IF EXISTS ' + nombre)

class Migration(migrations.Migration):
    dependencies = [('inventario', '0004_pagoproveedor'), ('tasas_bcv', '0001_initial'), ('liquidaciones', '0004_protecciones_comision_productos')]
    operations = [migrations.RunPython(instalar, retirar)]
