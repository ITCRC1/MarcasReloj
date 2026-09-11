from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.horarios.models import (
    AsignacionHorario,
    BloqueHorario,
    Feriado,
    Horario,
    Justificacion,
)


class BloqueInline(admin.TabularInline):
    model = BloqueHorario
    extra = 0


@admin.register(Horario)
class HorarioAdmin(SimpleHistoryAdmin):
    list_display = ["nombre", "tipo_jornada", "tolerancia_entrada_min", "minimo_extra_min", "activo"]
    inlines = [BloqueInline]


@admin.register(AsignacionHorario)
class AsignacionAdmin(SimpleHistoryAdmin):
    list_display = ["empleado", "horario", "vigente_desde", "vigente_hasta"]
    list_filter = ["horario"]
    search_fields = ["empleado__nombre", "empleado__codigo_planilla"]


@admin.register(Feriado)
class FeriadoAdmin(SimpleHistoryAdmin):
    list_display = ["fecha", "nombre"]


@admin.register(Justificacion)
class JustificacionAdmin(SimpleHistoryAdmin):
    list_display = ["empleado", "tipo", "desde", "hasta", "registrada_por"]
    list_filter = ["tipo"]
    search_fields = ["empleado__nombre"]
