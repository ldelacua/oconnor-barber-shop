from django.apps import AppConfig
from django.conf import settings

class SeguridadConfig(AppConfig):
    name='seguridad'

    def ready(self):
        from . import checks  # Registra la comprobación obligatoria de instalación.
        # El Admin solo administra autenticación y seguridad. Quita también
        # las rutas de edición directa, no únicamente los enlaces del índice.
        from django.contrib import admin
        for modelo in list(admin.site._registry):
            if modelo._meta.label_lower == "ventas.tarjetaregalo" and getattr(settings, "PROMOCIONES_FIDELIDAD", False):
                continue
            if (modelo._meta.label_lower in {'ventas.tarjetafidelidad', 'ventas.entidadconvenio', 'ventas.promocionservicio'}
                    and getattr(settings, 'PROMOCIONES_FIDELIDAD', False)):
                continue
            if modelo._meta.app_label not in {'auth','seguridad'}:
                admin.site.unregister(modelo)
