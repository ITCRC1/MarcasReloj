from django.db import models

from apps.core.models import generar_api_key


class ClienteAPI(models.Model):
    """Consumidor de solo lectura, tipicamente el sistema de planillas.

    Sus claves son distintas a las de los agentes: un agente solo puede escribir
    en la ingesta y un cliente solo puede leer.
    """

    nombre = models.CharField("nombre", max_length=100)
    api_key_hash = models.CharField(max_length=64, unique=True, blank=True, db_index=True)
    api_key_prefijo = models.CharField(max_length=16, blank=True)
    activo = models.BooleanField("activo", default=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)

    class Meta:
        verbose_name = "cliente de API"
        verbose_name_plural = "clientes de API"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def rotar_api_key(self) -> str:
        clave, hash_, prefijo = generar_api_key("pl")
        self.api_key_hash = hash_
        self.api_key_prefijo = prefijo
        self.save(update_fields=["api_key_hash", "api_key_prefijo"])
        return clave
