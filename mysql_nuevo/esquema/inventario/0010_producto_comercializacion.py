from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventario", "0009_grupoproducto_producto_grupo")]

    operations = [
        migrations.AddField(
            model_name="producto", name="comercializacion",
            field=models.BooleanField("Comercialización", default=True),
        ),
    ]
