from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("clientes/", include("clientes.urls")),
    path("citas/", include("citas.urls")),
    path("tasas-bcv/", include("tasas_bcv.urls")),
]