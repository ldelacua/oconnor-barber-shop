import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('seguridad', '0002_alter_auditoria_options_alter_usuario_options_and_more'), ('barberos', '0001_initial')]
    operations = [migrations.AddField(model_name='usuario', name='prestador',
        field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                   related_name='cuenta_usuario', to='barberos.barbero', verbose_name='Prestador de servicio'))]
