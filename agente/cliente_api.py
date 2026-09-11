"""Envio de lotes al servidor, con reintentos y espera creciente."""

import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

ESPERA_MAXIMA_SEG = 300


class ClienteAPI:
    def __init__(self, url_base: str, api_key: str, nombre_agente: str, tiempo_limite=30):
        self.url = url_base.rstrip("/") + "/api/v1/ingesta/marcas"
        self.salud = url_base.rstrip("/") + "/api/v1/salud"
        self.api_key = api_key
        self.nombre_agente = nombre_agente
        self.tiempo_limite = tiempo_limite
        self.sesion = requests.Session()
        self.sesion.headers.update(
            {"X-API-Key": api_key, "Content-Type": "application/json"}
        )

    def enviar(self, marcas: list[dict]) -> dict | None:
        """Devuelve el conteo del servidor, o None si el envio fallo.

        Un lote vacio tambien se envia: le sirve al servidor como latido.
        """
        lote = {
            "agente": self.nombre_agente,
            "enviado_en": datetime.now(timezone.utc).isoformat(),
            "marcas": marcas,
        }
        try:
            respuesta = self.sesion.post(self.url, json=lote, timeout=self.tiempo_limite)
        except requests.RequestException as error:
            log.warning("No se pudo contactar al servidor: %s", error)
            return None

        if respuesta.status_code == 200:
            return respuesta.json()
        if respuesta.status_code in (401, 403):
            log.error(
                "El servidor rechazo la clave o el nombre del agente (%s): %s",
                respuesta.status_code, respuesta.text[:200],
            )
            return None
        log.warning("El servidor respondio %s: %s", respuesta.status_code, respuesta.text[:200])
        return None

    def esta_vivo(self) -> bool:
        try:
            return self.sesion.get(self.salud, timeout=10).status_code == 200
        except requests.RequestException:
            return False


def siguiente_espera(espera_actual: int, intervalo: int) -> int:
    """Espera creciente hasta un maximo de 5 minutos."""
    return min(max(espera_actual * 2, intervalo), ESPERA_MAXIMA_SEG)
