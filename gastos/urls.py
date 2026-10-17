from django.urls import path
from . import views
app_name="gastos"
urlpatterns=[
    path("",views.inicio,name="inicio"),
    path("nuevo/",views.formulario_registro,name="crear"),
    path("<int:pk>/",views.ver_registro,name="ver"),
    path("<int:pk>/editar/",views.formulario_registro,name="editar"),
    path("<int:pk>/eliminar/",views.eliminar_registro,name="eliminar"),
    path("catalogos/<str:catalogo>/",views.lista_catalogo,name="catalogo"),
    path("catalogos/<str:catalogo>/nuevo/",views.formulario_catalogo,name="catalogo_crear"),
    path("catalogos/<str:catalogo>/<int:pk>/editar/",views.formulario_catalogo,name="catalogo_editar"),
    path("catalogos/<str:catalogo>/<int:pk>/estado/",views.estado_catalogo,name="catalogo_estado"),
    path("catalogos/<str:catalogo>/<int:pk>/eliminar/",views.eliminar_catalogo,name="catalogo_eliminar"),
]
