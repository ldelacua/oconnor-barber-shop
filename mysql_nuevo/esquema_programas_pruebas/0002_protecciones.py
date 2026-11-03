from django.db import migrations
from mysql_nuevo.instalacion import instalar

def instalar_para_pruebas(apps, schema_editor):
    instalar(apps, schema_editor, con_disparadores=False)

class Migration(migrations.Migration):
    atomic=False
    dependencies=[('seguridad', '0001_initial'), ('clientes', '0001_initial'), ('barberos', '0002_initial'), ('servicios', '0001_initial'), ('horarios', '0001_initial'), ('citas', '0001_initial'), ('tasas_bcv', '0001_initial'), ('ventas', '0001_initial'), ('liquidaciones', '0001_initial'), ('gastos', '0001_initial'), ('inventario', '0001_initial'), ('ventas_productos', '0001_initial'), ('control_inventario', '0001_initial'), ('mysql_nuevo', '0001_initial')]
    operations=[migrations.RunPython(instalar_para_pruebas)]
