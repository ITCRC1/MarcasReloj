from django.contrib import admin

from apps.core.models import Empleado


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = [
        "codigo_planilla", "nombre", "person_id_smartpss", "departamento",
        "horario", "activo",
    ]
    list_filter = ["activo", "departamento", "horario"]
    search_fields = ["codigo_planilla", "nombre", "person_id_smartpss", "identificacion"]
