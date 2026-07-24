from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("autenticacion.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("clientes/", include("clientes.urls")),
    path("barberos/", include("barberos.urls")),
]


