from django.apps import AppConfig

class MysqlNuevoConfig(AppConfig):
    name='mysql_nuevo'
    verbose_name='Infraestructura MySQL'

    def ready(self):
        from . import checks
