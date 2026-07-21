from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Auditoria, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "groups",
    )

    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
        "telefono",
    )

    fieldsets = UserAdmin.fieldsets + (
        (
            "Información adicional",
            {
                "fields": (
                    "telefono",
                )
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Información adicional",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "telefono",
                )
            },
        ),
    )


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "accion",
        "fecha",
    )

    list_filter = (
        "fecha",
    )

    search_fields = (
        "usuario__username",
        "usuario__first_name",
        "usuario__last_name",
        "accion",
    )

    readonly_fields = (
        "usuario",
        "accion",
        "fecha",
    )

    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser