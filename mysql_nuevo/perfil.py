"""Activa únicamente las migraciones nuevas; SQLite mantiene su historial propio."""
APPS = ['seguridad','clientes','barberos','servicios','horarios','citas','tasas_bcv','ventas','liquidaciones','gastos','inventario','ventas_productos','control_inventario']
MIGRACIONES = {app:'mysql_nuevo.esquema.'+app for app in APPS}
