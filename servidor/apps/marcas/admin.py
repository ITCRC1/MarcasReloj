from django.contrib import admin

from apps.marcas.models import MarcaManual, MarcaReloj


@admin.register(MarcaReloj)
class MarcaRelojAdmin(admin.ModelAdmin):
    list_display = ["fecha_hora", "person_id", "empleado", "device_name", "anulada", "handler"]
    list_filter = ["anulada", "fecha_local"]
    search_fields = ["person_id", "person_name", "empleado__nombre"]
    date_hierarchy = "fecha_local"
    # No se editan nunca: se anulan desde la pantalla del dia.
    readonly_fields = [c.name for c in MarcaReloj._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarcaManual)
class MarcaManualAdmin(admin.ModelAdmin):
    list_display = ["fecha_hora", "empleado", "motivo", "anulada", "creada_por"]
    list_filter = ["anulada", "motivo"]
    search_fields = ["empleado__nombre", "detalle"]
    date_hierarchy = "fecha_local"
