from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from apps.core.models import Departamento, Empleado, Sucursal


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo_agente", "api_key_prefijo", "ultima_sincronizacion", "activa"]
    readonly_fields = ["api_key_hash", "api_key_prefijo", "ultima_sincronizacion"]
    actions = ["generar_clave"]

    @admin.action(description="Generar clave de API nueva")
    def generar_clave(self, request, queryset):
        for sucursal in queryset:
            clave = sucursal.rotar_api_key()
            self.message_user(
                request,
                f"{sucursal.nombre}: {clave}  (copiela ahora, no se vuelve a mostrar)",
                level=messages.WARNING,
            )


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "sucursal"]
    list_filter = ["sucursal"]
    filter_horizontal = ["supervisores"]


@admin.register(Empleado)
class EmpleadoAdmin(SimpleHistoryAdmin):
    list_display = ["codigo_planilla", "nombre", "person_id_smartpss", "departamento", "activo"]
    list_filter = ["activo", "departamento"]
    search_fields = ["codigo_planilla", "nombre", "person_id_smartpss", "identificacion"]
