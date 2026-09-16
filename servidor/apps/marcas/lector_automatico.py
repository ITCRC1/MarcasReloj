"""Trae las marcas de SmartPSS sola, cada cierto rato, sin que nadie la llame.

Sin esto el sistema solo importa cuando alguien corre `manage.py leer_smartpss`
a mano, que en Railway no pasa nunca: ahi solo se levanta el servidor web. Las
marcas se quedaban del otro lado sin que nada avisara.

Es un hilo dentro del mismo proceso web en vez de un servicio aparte porque el
sistema es pequeno, SmartPSS escribe en esta misma base y un servicio mas seria
otra cosa que configurar, que pagar y que se puede caer sin que se note.

Si hay varios workers de gunicorn, cada uno levanta su hilo. No importa: la
ingesta descarta lo repetido por la llave unica de la marca. El desfase del
arranque es para que no consulten todos en el mismo instante.
"""

import logging
import random
import threading
import time

from django.conf import settings
from django.db import close_old_connections

log = logging.getLogger(__name__)

PUESTA_AL_DIA_SEG = 30 * 60

_hilo: threading.Thread | None = None
_candado = threading.Lock()


def _ciclo() -> None:
    intervalo = settings.SMARTPSS_INTERVALO_SEG
    # Desfase para que los workers no caigan todos en el mismo segundo, y para
    # no competir con el arranque del servidor.
    time.sleep(random.uniform(5, min(20, intervalo)))

    ultima_puesta_al_dia = None

    while True:
        try:
            # El hilo vive horas; las conexiones que Django deja abiertas se
            # caducan del lado de MySQL y la siguiente consulta falla.
            close_old_connections()
            from apps.marcas import importador

            tabla = settings.SMARTPSS_TABLA
            resultado = importador.una_pasada(tabla)

            # Si aun asi SmartPSS tiene mas marcas que el sistema, son viejas y
            # quedaron fuera de la ventana. Releer todo cuesta, asi que se hace
            # a lo sumo cada media hora.
            if importador.pendientes(tabla) and (
                ultima_puesta_al_dia is None
                or time.monotonic() - ultima_puesta_al_dia > PUESTA_AL_DIA_SEG
            ):
                ultima_puesta_al_dia = time.monotonic()
                extra = importador.ponerse_al_dia(tabla)
                resultado["nuevas"] += extra["nuevas"]
                resultado["sin_empleado"] += extra["sin_empleado"]

            if resultado["nuevas"]:
                log.info(
                    "SmartPSS: %s marcas nuevas, %s sin empleado",
                    resultado["nuevas"], resultado["sin_empleado"],
                )
        except Exception:  # noqa: BLE001 - un fallo no puede matar el hilo
            log.exception("SmartPSS: fallo una pasada de lectura")
        finally:
            close_old_connections()
        time.sleep(intervalo)


def debe_arrancar() -> tuple[bool, str]:
    """Si corresponde leer solo, y si no, por que no. Separado para poder probarlo."""
    if not settings.SMARTPSS_AUTO:
        return False, "SMARTPSS_AUTO esta apagado"
    if not settings.SMARTPSS_TABLA:
        return False, "falta SMARTPSS_TABLA"
    return True, ""


def arrancar() -> bool:
    """Levanta el hilo una sola vez por proceso. Devuelve si quedo corriendo."""
    global _hilo

    puede, motivo = debe_arrancar()
    if not puede:
        log.info("SmartPSS: no se lee automaticamente porque %s", motivo)
        return False

    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return True
        _hilo = threading.Thread(target=_ciclo, name="leer-smartpss", daemon=True)
        _hilo.start()

    log.info(
        "SmartPSS: leyendo '%s' cada %s s",
        settings.SMARTPSS_TABLA, settings.SMARTPSS_INTERVALO_SEG,
    )
    return True
