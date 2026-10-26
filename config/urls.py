from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("control-inventario/", include("control_inventario.urls")),
    path("ventas-productos/", include("ventas_productos.urls")),
    path("inventario/", include("inventario.urls")),
    path("admin/", admin.site.urls),
    path("", include("autenticacion.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("clientes/", include("clientes.urls")),
    path("barberos/", include("barberos.urls")),
    path("servicios/", include("servicios.urls")),
    path("horarios/", include("horarios.urls")),
    path("citas/", include("citas.urls")),
    path("tasas-bcv/", include("tasas_bcv.urls")),
    path("ventas/", include("ventas.urls")),
    path("liquidaciones/", include("liquidaciones.urls")),
    path("gastos/", include("gastos.urls")),
]


