"""Autenticacion por X-API-Key.

Las claves de los agentes (Sucursal) y las de los consumidores (ClienteAPI) son
distintas y no se cruzan: un agente solo escribe en la ingesta, un cliente solo lee.
"""

from django.utils import timezone
from ninja.security import APIKeyHeader

from apps.api.models import ClienteAPI
from apps.core.models import Sucursal, hash_api_key


class ClaveDeAgente(APIKeyHeader):
    param_name = "X-API-Key"

    def authenticate(self, request, key):
        if not key:
            return None
        sucursal = Sucursal.objects.filter(
            api_key_hash=hash_api_key(key), activa=True
        ).first()
        if sucursal is None:
            return None
        request.sucursal = sucursal
        return sucursal


class ClaveDeCliente(APIKeyHeader):
    param_name = "X-API-Key"

    def authenticate(self, request, key):
        if not key:
            return None
        cliente = ClienteAPI.objects.filter(
            api_key_hash=hash_api_key(key), activo=True
        ).first()
        if cliente is None:
            return None
        cliente.ultimo_uso = timezone.now()
        cliente.save(update_fields=["ultimo_uso"])
        request.cliente_api = cliente
        return cliente


clave_de_agente = ClaveDeAgente()
clave_de_cliente = ClaveDeCliente()
