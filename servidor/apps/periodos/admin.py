from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.periodos.models import Ajuste, Periodo


@admin.register(Periodo)
class PeriodoAdmin(SimpleHistoryAdmin):
    list_display = ["nombre", "desde", "hasta", "estado", "cerrado_por", "cerrado_en"]
    list_filter = ["estado"]


@admin.register(Ajuste)
class AjusteAdmin(SimpleHistoryAdmin):
    list_display = ["empleado", "periodo_destino", "concepto", "minutos", "fecha_original"]
    list_filter = ["concepto", "periodo_destino"]
    search_fields = ["empleado__nombre", "motivo"]
