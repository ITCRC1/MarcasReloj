from django.contrib import admin

from apps.horarios.models import BloqueHorario, Feriado, Horario


class BloqueInline(admin.TabularInline):
    model = BloqueHorario
    extra = 0


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tolerancia_entrada_min", "minimo_extra_min", "activo"]
    inlines = [BloqueInline]


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "nombre"]
