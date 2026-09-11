from django.contrib import admin, messages

from apps.api.models import ClienteAPI


@admin.register(ClienteAPI)
class ClienteAPIAdmin(admin.ModelAdmin):
    list_display = ["nombre", "api_key_prefijo", "activo", "ultimo_uso"]
    readonly_fields = ["api_key_hash", "api_key_prefijo", "ultimo_uso"]
    actions = ["generar_clave"]

    @admin.action(description="Generar clave de API nueva")
    def generar_clave(self, request, queryset):
        for cliente in queryset:
            clave = cliente.rotar_api_key()
            self.message_user(
                request,
                f"{cliente.nombre}: {clave}  (copiela ahora, no se vuelve a mostrar)",
                level=messages.WARNING,
            )
