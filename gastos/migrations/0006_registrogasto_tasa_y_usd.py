from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gastos", "0005_detalleregistrogasto_impuesto_linea_and_more")]

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
