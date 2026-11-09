from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventario", "0010_producto_sin_comision")]

    operations = [
        migrations.CreateModel(
            name="GrupoProducto",
            fields=[
                ("id_grupo", models.BigAutoField(primary_key=True, serialize=False)),
                ("descripcion", models.CharField("Descripción", max_length=150, unique=True)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={"ordering": ["descripcion", "pk"]},
        ),
        migrations.AddField(
            model_name="producto", name="grupo",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    to="inventario.grupoproducto", verbose_name="Grupo"),
        ),
    ]
