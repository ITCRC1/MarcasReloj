"""Conversiones de tiempo. Un solo lugar para no repetir la regla en cada app."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

CR = ZoneInfo("America/Costa_Rica")


def utc_ms_a_datetime(utc_ms: int) -> datetime:
    """Milisegundos UTC de SmartPSS a datetime aware en UTC."""
    return datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc)


def a_local(dt: datetime) -> datetime:
    return dt.astimezone(CR)


def fecha_local(dt: datetime) -> date:
    """Fecha calendario en Costa Rica, usada para agrupar marcas por dia."""
    return dt.astimezone(CR).date()


def datetime_local(fecha: date, hora) -> datetime:
    """Combina fecha y hora en un datetime aware de Costa Rica."""
    return datetime.combine(fecha, hora).replace(tzinfo=CR)


def formato_hm(minutos: int | None) -> str:
    """Minutos enteros a 'H:MM'. Es como se muestra el tiempo en pantalla y PDF."""
    if minutos is None:
        return "-"
    signo = "-" if minutos < 0 else ""
    minutos = abs(int(minutos))
    return f"{signo}{minutos // 60}:{minutos % 60:02d}"


def excel_tiempo(minutos: int | None) -> float:
    """Minutos a fraccion de dia, para escribir en Excel con formato [h]:mm."""
    return 0.0 if not minutos else minutos / 1440
