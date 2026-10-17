from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("citas", "0002_cita_servicios")]
    operations = [
        migrations.AlterField(
            model_name="cita",
            name="barbero",
            field=models.ForeignKey(
                to="barberos.barbero",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="citas",
                verbose_name="Prestador de Servicio",
            ),
        ),
    ]
