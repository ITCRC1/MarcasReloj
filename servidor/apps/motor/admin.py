from django.contrib import admin

from apps.motor.models import ResultadoDiario


@admin.register(ResultadoDiario)
class ResultadoDiarioAdmin(admin.ModelAdmin):
    list_display = [
        "fecha", "empleado", "estado", "minutos_ordinarios", "minutos_extra",
        "minutos_tardia", "minutos_no_laborados", "aceptado_por",
    ]
    list_filter = ["estado", "fecha"]
    search_fields = ["empleado__nombre", "empleado__codigo_planilla"]
    date_hierarchy = "fecha"
    # Se regenera en cada recalculo: editarlo a mano no tendria efecto duradero.
    readonly_fields = [c.name for c in ResultadoDiario._meta.fields]

    def has_add_permission(self, request):
        return False
