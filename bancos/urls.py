from django.urls import path
from . import views
app_name = 'bancos'
urlpatterns = [
    path('', views.lista, name='lista'),
    path('cuenta/<int:pk>/estado/', views.estado_cuenta, name='estado_cuenta'),
    path('cuenta/<int:pk>/reporte/', views.reporte_cuenta, name='reporte_cuenta'),
    path('cuenta/<int:pk>/conciliar/', views.conciliar_cuenta, name='conciliar_cuenta'),
    path('vincular/', views.vincular_pago, name='vincular_pago'),
    path('importar/', views.importar_estado, name='importar_estado'),
    path('banco/nuevo/', views.editar, {'tipo': 'banco'}, name='nuevo_banco'),
    path('banco/<int:pk>/', views.editar, {'tipo': 'banco'}, name='editar_banco'),
    path('cuenta/nueva/', views.editar, {'tipo': 'cuentabancaria'}, name='nueva_cuenta'),
    path('cuenta/<int:pk>/', views.editar, {'tipo': 'cuentabancaria'}, name='editar_cuenta'),
]
