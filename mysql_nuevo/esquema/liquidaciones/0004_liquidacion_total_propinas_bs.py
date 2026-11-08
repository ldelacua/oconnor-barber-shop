from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("liquidaciones", "0003_protecciones_comision"),
        ("ventas", "0009_detalleventa_propina_bs"),
    ]
    operations = [
        migrations.AddField("liquidacion", "total_propinas_bs",
                            models.DecimalField(max_digits=18, decimal_places=2, default=0)),
    ]
