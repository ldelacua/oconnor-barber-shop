from django.urls import path
from . import views
app_name = 'bancos'
urlpatterns = [
    path('', views.lista, name='lista'),
    path('cuenta/<int:pk>/estado/', views.estado_cuenta, name='estado_cuenta'),
    path('cuenta/<int:pk>/reporte/', views.reporte_cuenta, name='reporte_cuenta'),
    path('cuenta/<int:pk>/conciliar/', views.conciliar_cuenta, name='conciliar_cuenta'),
    path('cuenta/<int:pk>/conciliar/cargo/<int:movimiento_id>/', views.registrar_cargo_bancario, name='registrar_cargo_bancario'),
    path('cuenta/<int:pk>/conciliar/cargo/<int:movimiento_id>/anular/', views.anular_cargo_bancario, name='anular_cargo_bancario'),
    path('vincular/', views.vincular_pago, name='vincular_pago'),
    path('importar/', views.importar_estado, name='importar_estado'),
    path('carga-manual/', views.cargar_movimiento, name='cargar_movimiento'),
    path('movimiento/<int:pk>/editar/', views.corregir_movimiento_banco, name='editar_movimiento'),
    path('movimiento/<int:pk>/eliminar/', views.corregir_movimiento_banco, {'eliminar': True}, name='eliminar_movimiento'),
    path('banco/nuevo/', views.editar, {'tipo': 'banco'}, name='nuevo_banco'),
    path('banco/<int:pk>/formato-estado/', views.formato_estado, name='formato_estado'),
    path('banco/<int:pk>/', views.editar, {'tipo': 'banco'}, name='editar_banco'),
    path('cuenta/nueva/', views.editar, {'tipo': 'cuentabancaria'}, name='nueva_cuenta'),
    path('cuenta/<int:pk>/', views.editar, {'tipo': 'cuentabancaria'}, name='editar_cuenta'),
]
