from django.urls import path
from . import views
app_name="liquidaciones"
urlpatterns=[
    path("",views.lista,name="lista"),
    path("nueva/",views.crear,name="crear"),
    path("<int:pk>/",views.ver,name="ver"),
]
