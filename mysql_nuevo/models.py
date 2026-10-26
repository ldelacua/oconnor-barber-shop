from django.db import models

class CandadoOperaciones(models.Model):
    id=models.PositiveSmallIntegerField(primary_key=True)
    class Meta:
        db_table='mysql_candado_operaciones'
        default_permissions=()
