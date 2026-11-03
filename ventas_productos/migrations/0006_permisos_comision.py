from importlib import import_module
from django.db import migrations
helpers = import_module('ventas_productos.migrations._permisos_comision')
class Migration(migrations.Migration):
    dependencies = [('ventas_productos', '0005_escalacomisionproducto'), ('auth', '0012_alter_user_first_name_max_length')]
    operations = [migrations.RunPython(helpers.instalar, migrations.RunPython.noop)]
