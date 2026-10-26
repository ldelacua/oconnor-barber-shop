from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.iniciar_sesion, name="iniciar_sesion"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("cerrar-sesion/", views.cerrar_sesion, name="cerrar_sesion"),
    path("cuenta/cambiar-clave/", auth_views.PasswordChangeView.as_view(
        template_name="autenticacion/clave_form.html",
        success_url=reverse_lazy("clave_cambiada"),
        extra_context={"titulo": "Cambiar contraseña", "cambio": True},
    ), name="cambiar_clave"),
    path("cuenta/clave-cambiada/", auth_views.PasswordChangeDoneView.as_view(
        template_name="autenticacion/clave_mensaje.html",
        extra_context={"titulo": "Contraseña actualizada", "texto": "Tu contraseña fue cambiada correctamente. Tu sesión continúa abierta."},
    ), name="clave_cambiada"),
    path("recuperar-clave/", auth_views.PasswordResetView.as_view(
        template_name="autenticacion/clave_form.html",
        email_template_name="autenticacion/clave_email.txt",
        subject_template_name="autenticacion/clave_asunto.txt",
        success_url=reverse_lazy("recuperar_clave_enviada"),
        extra_context={"titulo": "Recuperar contraseña", "recuperar": True},
    ), name="recuperar_clave"),
    path("recuperar-clave/enviada/", auth_views.PasswordResetDoneView.as_view(
        template_name="autenticacion/clave_mensaje.html",
        extra_context={"titulo": "Revisa tu correo", "texto": "Si el correo corresponde a un usuario activo, recibirás un enlace para cambiar tu contraseña. Revisa también la carpeta de spam."},
    ), name="recuperar_clave_enviada"),
    path("recuperar-clave/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="autenticacion/clave_confirmar.html",
        success_url=reverse_lazy("recuperar_clave_completa"),
    ), name="recuperar_clave_confirmar"),
    path("clave-restablecida/", auth_views.PasswordResetCompleteView.as_view(
        template_name="autenticacion/clave_mensaje.html",
        extra_context={"titulo": "Contraseña restablecida", "texto": "Ya puedes iniciar sesión con tu nueva contraseña."},
    ), name="recuperar_clave_completa"),
]
