from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clientes", "0002_telefono_unico")]
    operations = [
        migrations.AddField("cliente", "clave_portal",
                            models.CharField(max_length=128, blank=True, default="", editable=False)),
    ]
