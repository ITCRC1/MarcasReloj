"""Una pasada de importacion: de donde leer y que traer.

Vive aparte del comando porque lo usan dos: `manage.py leer_smartpss`, para
correrlo a mano, y el lector automatico que arranca con el servidor. Si la
regla de la marca de agua estuviera duplicada, tarde o temprano una de las dos
se quedaria atras.
"""

from datetime import date, datetime

from django.conf import settings
from django.db.models import Max

from apps.core.tiempo import CR
from apps.marcas import lector_directo
from apps.marcas.models import MarcaReloj
from apps.marcas.servicio import adoptar_marcas_sin_empleado, ingestar

LOTE_MAX = 2000


class FechaInvalida(ValueError):
    """La fecha de inicio no tiene el formato AAAA-MM-DD."""


def _inicio_del_dia(dia: date) -> int:
    return int(datetime(dia.year, dia.month, dia.day, tzinfo=CR).timestamp() * 1000)


def marca_de_agua(desde: str | None = None) -> int:
    """Desde que milisegundo UTC leer.

    Se relee hacia atras porque SmartPSS puede escribir marcas con horas pasadas
    cuando vuelve de estar cerrado. Los duplicados los descarta la ingesta, asi
    que releer nunca hace dano.
    """
    if desde:
        try:
            return _inicio_del_dia(date.fromisoformat(desde))
        except ValueError:
            raise FechaInvalida(f"'{desde}' no es una fecha AAAA-MM-DD")

    ultimo = MarcaReloj.objects.aggregate(tope=Max("utc_ms"))["tope"]
    if ultimo is not None:
        return ultimo - settings.SMARTPSS_VENTANA_HORAS * 3600 * 1000

    if settings.SMARTPSS_FECHA_INICIO:
        return _inicio_del_dia(date.fromisoformat(settings.SMARTPSS_FECHA_INICIO))
    return 0


def una_pasada(tabla: str, desde: str | None = None, desde_ms: int | None = None) -> dict:
    """Lee lo que haya nuevo y lo ingesta. Devuelve el conteo sumado de la ingesta.

    Lee por lotes hasta vaciar: la primera vez SmartPSS subio mas de 3.000
    marcas de historial de un solo golpe, y un lote unico se quedaba corto.
    """
    lector_directo.validar_nombre(tabla)
    punto = marca_de_agua(desde) if desde_ms is None else desde_ms
    total = {
        "recibidas": 0, "nuevas": 0, "duplicadas": 0, "sin_empleado": 0,
        # Marcas importadas antes de que los empleados se crearan solos.
        "empleados_creados": adoptar_marcas_sin_empleado(),
    }

    while True:
        marcas = lector_directo.leer_desde(tabla, punto, LOTE_MAX)
        for clave, valor in ingestar(marcas).items():
            total[clave] = total.get(clave, 0) + valor
        if len(marcas) < LOTE_MAX:
            return total
        siguiente = max(m["utc_ms"] for m in marcas)
        # Sin avance no hay forma de salir: seria un lote entero en el mismo
        # milisegundo. No pasa con marcas reales, pero no puede colgar el hilo.
        if siguiente <= punto:
            return total
        punto = siguiente


def ponerse_al_dia(tabla: str) -> dict:
    """Relee toda la tabla. Para cuando SmartPSS sube marcas mas viejas que la ventana.

    La pasada normal solo mira las ultimas horas. Si SmartPSS estuvo apagado
    unos dias, o sube historial al activarlo, esas marcas quedan atras de la
    ventana y nunca se leerian. Los duplicados los descarta la ingesta.
    """
    inicio = 0
    if settings.SMARTPSS_FECHA_INICIO:
        inicio = _inicio_del_dia(date.fromisoformat(settings.SMARTPSS_FECHA_INICIO))
    return una_pasada(tabla, desde_ms=inicio)


def pendientes(tabla: str) -> int | None:
    """Cuantas marcas escribio SmartPSS que el sistema todavia no tiene.

    Es el numero que dice si la importacion esta viva. Devuelve None si la tabla
    no esta configurada o no se puede leer, porque eso ya lo avisa otra alerta.
    """
    try:
        lector_directo.validar_nombre(tabla)
        return max(0, lector_directo.total_de(tabla) - MarcaReloj.objects.count())
    except Exception:  # noqa: BLE001 - es un indicador, no puede tumbar la pantalla
        return None
