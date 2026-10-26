from django.urls import path
from . import views
from .buscador_productos import buscar_productos

app_name = "inventario"
urlpatterns = [
    path("productos/buscar/", buscar_productos, name="buscar_productos"),
    path("compras/condiciones/", views.condiciones_compra, name="condiciones"),
    path("unidades/", views.maestro_lista, {"tipo": "unidades"}, name="unidades"),
    path("unidades/nueva/", views.maestro_form, {"tipo": "unidades"}, name="nueva_unidad"),
    path("unidades/<int:pk>/editar/", views.maestro_form, {"tipo": "unidades"}, name="editar_unidad"),
    path("", views.compras, name="compras"),
    path("compras/nueva/", views.compra_form, name="nueva_compra"),
    path("compras/<int:pk>/", views.detalle, name="detalle"),
    path("compras/<int:pk>/editar/", views.compra_form, name="editar_compra"),
    path("compras/<int:pk>/actualizar/", views.actualizar, name="actualizar"),
    path("compras/<int:pk>/eliminar/", views.eliminar, name="eliminar"),
    path("productos/", views.maestro_lista, {"tipo": "productos"}, name="productos"),
    path("productos/nuevo/", views.maestro_form, {"tipo": "productos"}, name="nuevo_producto"),
    path("productos/<int:pk>/editar/", views.maestro_form, {"tipo": "productos"}, name="editar_producto"),
    path("proveedores/", views.maestro_lista, {"tipo": "proveedores"}, name="proveedores"),
    path("proveedores/nuevo/", views.maestro_form, {"tipo": "proveedores"}, name="nuevo_proveedor"),
    path("proveedores/<int:pk>/editar/", views.maestro_form, {"tipo": "proveedores"}, name="editar_proveedor"),
]
