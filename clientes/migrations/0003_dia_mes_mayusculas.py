from django.db import migrations, models
import django.core.validators


def convertir_clientes(apps, schema_editor):
    Cliente = apps.get_model("clientes", "Cliente")
    alias = schema_editor.connection.alias
    for cliente in Cliente.objects.using(alias).iterator():
        datos = {}
        for campo in ("nombre", "apellido", "direccion", "email", "observaciones"):
            valor = getattr(cliente, campo)
            if valor is not None:
                datos[campo] = valor.upper()
        if cliente.fecha_nacimiento:
            datos["dia_nacimiento"] = cliente.fecha_nacimiento.day
            datos["mes_nacimiento"] = cliente.fecha_nacimiento.month
        Cliente.objects.using(alias).filter(pk=cliente.pk).update(**datos)


class Migration(migrations.Migration):
    dependencies = [("clientes", "0002_remove_cliente_codigo_remove_cliente_correo_and_more")]
    operations = [
        migrations.AddField(model_name="cliente", name="dia_nacimiento",
                            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="cliente", name="mes_nacimiento",
                            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        # Solo cambia el estado de validación: no reconstruye la tabla SQLite.
        migrations.SeparateDatabaseAndState(state_operations=[
            migrations.AlterField(model_name="cliente", name="fecha_nacimiento",
                field=models.DateField(blank=True, null=True, editable=False)),
            migrations.AlterField(model_name="cliente", name="telefono",
                field=models.CharField(max_length=20, validators=[
                    django.core.validators.RegexValidator(
                        r"\A[0-9]{10}\Z", "El teléfono debe contener exactamente 10 dígitos (0-9).")]))
        ], database_operations=[]),
        migrations.RunPython(convertir_clientes, migrations.RunPython.noop),
    ]
