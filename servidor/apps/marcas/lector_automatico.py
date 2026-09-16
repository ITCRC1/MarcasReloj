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
import sys
import threading
import time

from django.conf import settings
from django.db import close_old_connections

log = logging.getLogger(__name__)

PUESTA_AL_DIA_SEG = 30 * 60

_hilo: threading.Thread | None = None
_candado = threading.Lock()

# Lo que se sabe del lector en este proceso. Lo muestra /estado-lector/, porque
# la vez que no arranco no hubo forma de saberlo sin entrar a la bitacora.
ESTADO = {
    "no_arranco_porque": "",
    "arrancado_en": None,
    "ultima_pasada": None,
    "nuevas_en_la_ultima": 0,
    "ultimo_error": "",
    "ultimo_error_en": None,
}


def _ahora() -> str:
    from django.utils import timezone

    return timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")


def esta_vivo() -> bool:
    return _hilo is not None and _hilo.is_alive()


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

            ESTADO["ultima_pasada"] = _ahora()
            ESTADO["nuevas_en_la_ultima"] = resultado["nuevas"]
            if resultado["nuevas"]:
                log.info(
                    "SmartPSS: %s marcas nuevas, %s sin empleado",
                    resultado["nuevas"], resultado["sin_empleado"],
                )
        except Exception as error:  # noqa: BLE001 - un fallo no puede matar el hilo
            # Solo el tipo y el mensaje: la pagina de estado no pide sesion.
            ESTADO["ultimo_error"] = f"{type(error).__name__}: {str(error)[:200]}"
            ESTADO["ultimo_error_en"] = _ahora()
            log.exception("SmartPSS: fallo una pasada de lectura")
        finally:
            close_old_connections()
        time.sleep(intervalo)


class ArrancarLectorMiddleware:
    """Respaldo: si el lector no arranco con el servidor, arranca con la primera visita.

    La deteccion de arranque mira como se lanzo el proceso, y una vez en Railway
    el lector no corrio sin que quedara claro por que. Con esto basta que alguien
    abra cualquier pagina. Revisar si el hilo vive no cuesta nada.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not esta_vivo() and "pytest" not in sys.modules:
            arrancar()
        return self.get_response(request)


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
        ESTADO["no_arranco_porque"] = motivo
        log.warning("SmartPSS: no se lee automaticamente porque %s", motivo)
        return False

    with _candado:
        if esta_vivo():
            return True
        _hilo = threading.Thread(target=_ciclo, name="leer-smartpss", daemon=True)
        _hilo.start()
        ESTADO["no_arranco_porque"] = ""
        ESTADO["arrancado_en"] = _ahora()

    log.info(
        "SmartPSS: leyendo '%s' cada %s s",
        settings.SMARTPSS_TABLA, settings.SMARTPSS_INTERVALO_SEG,
    )
    return True
