from django.db import migrations
from mysql_nuevo.protecciones_reversos_pagos import instalar, permisos

class Migration(migrations.Migration):
    atomic = False
    dependencies = [('inventario', '0005_reversopagoproveedor')]
    operations = [migrations.RunPython(instalar), migrations.RunPython(permisos)]
