from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gastos", "0003_productos_facturables_importes")]

    operations = [
        migrations.AddField(
            model_name="registrogasto", name="tasa_bcv",
            field=models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="registrogasto", name="monto_usd",
            field=models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True, editable=False),
        ),
    ]
