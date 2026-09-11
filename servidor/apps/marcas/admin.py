from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.marcas.models import MarcaManual, MarcaReloj


@admin.register(MarcaReloj)
class MarcaRelojAdmin(SimpleHistoryAdmin):
    list_display = ["fecha_hora", "person_id", "empleado", "device_name", "anulada", "handler"]
    list_filter = ["anulada", "sucursal", "fecha_local"]
    search_fields = ["person_id", "person_name", "empleado__nombre"]
    date_hierarchy = "fecha_local"
    # Las marcas del reloj no se editan nunca: se anulan desde la pantalla del dia.
    readonly_fields = [c.name for c in MarcaReloj._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarcaManual)
class MarcaManualAdmin(SimpleHistoryAdmin):
    list_display = ["fecha_hora", "empleado", "motivo", "estado", "creada_por", "resuelta_por"]
    list_filter = ["estado", "motivo"]
    search_fields = ["empleado__nombre", "detalle"]
    date_hierarchy = "fecha_local"
