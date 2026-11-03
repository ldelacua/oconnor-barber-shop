import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('seguridad', '0001_initial'), ('barberos', '0001_initial')]
    operations = [migrations.AddField(model_name='usuario', name='prestador',
        field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                   related_name='cuenta_usuario', to='barberos.barbero', verbose_name='Prestador de servicio'))]
