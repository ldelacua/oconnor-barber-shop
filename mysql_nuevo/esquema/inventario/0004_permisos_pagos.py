from importlib import import_module
from django.db import migrations
helpers = import_module('inventario.migrations._permisos_pagos')
class Migration(migrations.Migration):
    dependencies = [('inventario', '0003_protecciones_pagos'), ('auth', '0012_alter_user_first_name_max_length')]
    operations = [migrations.RunPython(helpers.instalar, migrations.RunPython.noop)]
