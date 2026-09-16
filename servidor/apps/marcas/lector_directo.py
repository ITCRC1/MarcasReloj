"""Lectura de la tabla de SmartPSS cuando esta en la misma base del sistema.

Cuando SmartPSS escribe directamente en la base de este sistema, el agente sobra:
no hay nada que transportar de una maquina a otra. Este modulo lee esa tabla con
la conexion que ya tiene Django y entrega las marcas al mismo servicio de ingesta
que usa el agente, asi que las reglas de duplicados y de recalculo son identicas.

Sobre la tabla de SmartPSS solo se hace SELECT. Nunca se escribe ni se borra.
"""

import re
from datetime import datetime, timedelta, timezone

from django.db import connection

from apps.core.tiempo import CR

# Columnas que SmartPSS crea. El orden es el de su documentacion.
COLUMNAS = [
    "PersonID", "PersonName", "PerSonCardNo", "AttendanceDateTime", "AttendanceUtcTime",
    "AttendanceState", "AttendanceMethod", "DeviceIPAddress", "DeviceName",
    "SnapshotsPath", "Handler", "Remarks",
]

COLUMNA_FIRMA = "attendanceutctime"

# De donde sale la hora de una marca. Lo que muestra la instalacion real:
#
# - AttendanceUtcTime viene en SEGUNDOS (1789183484), no en milisegundos como
#   dice la documentacion. Y cuando SmartPSS sube el historial la deja en 0:
#   2.917 de las primeras 3.218 marcas llegaron asi.
# - AttendanceDateTime viene siempre, porque es parte de la llave primaria. Es
#   la hora de pared de Costa Rica escrita como si fuera un epoch UTC, en
#   milisegundos. En las 301 marcas que traian las dos, la diferencia fue
#   exactamente 6 horas en todas.
#
# Por eso se filtra y se ordena por AttendanceDateTime, que nunca falta, y la
# hora UTC sale de AttendanceUtcTime cuando viene, o de AttendanceDateTime
# interpretada en Costa Rica cuando no.
#
# Las dos se normalizan a milisegundos. El corte esta en 10^12, que en segundos
# seria el ano 33658 y en milisegundos el 2001: ninguna marca real cae cerca.
def _en_ms(columna: str) -> str:
    return f"CASE WHEN {columna} > 1000000000000 THEN {columna} ELSE {columna} * 1000 END"


LOCAL_EN_MS = _en_ms("AttendanceDateTime")
UTC_EN_MS = _en_ms("AttendanceUtcTime")

# El SELECT devuelve las dos columnas ya normalizadas, con su mismo nombre.
COLUMNAS_SELECT = [
    f"{LOCAL_EN_MS} AS AttendanceDateTime" if c == "AttendanceDateTime"
    else f"{UTC_EN_MS} AS AttendanceUtcTime" if c == "AttendanceUtcTime"
    else c
    for c in COLUMNAS
]

_EPOCH = datetime(1970, 1, 1)


def local_ms_a_utc_ms(local_ms: int) -> int:
    """AttendanceDateTime (hora de pared de Costa Rica como epoch) a epoch UTC."""
    pared = _EPOCH + timedelta(milliseconds=int(local_ms))
    return int(pared.replace(tzinfo=CR).timestamp() * 1000)


def utc_ms_a_local_ms(utc_ms: int) -> int:
    """Lo inverso: para comparar una marca de agua UTC contra AttendanceDateTime."""
    momento = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc).astimezone(CR)
    return int(utc_ms + momento.utcoffset().total_seconds() * 1000)


def utc_ms_de_la_fila(fila: dict) -> int:
    """La hora UTC de una marca, ya con sus columnas normalizadas a milisegundos."""
    utc = int(fila.get("AttendanceUtcTime") or 0)
    if utc > 0:
        return utc
    return local_ms_a_utc_ms(fila["AttendanceDateTime"])

# base.tabla o solo tabla. Nada mas: el nombre va literal en el SQL.
NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?$")


class TablaInvalida(ValueError):
    """El nombre de la tabla no es utilizable."""


def validar_nombre(tabla: str) -> str:
    """El nombre no puede ir parametrizado en el SQL, asi que se valida aparte."""
    if not tabla:
        raise TablaInvalida(
            "No se configuro SMARTPSS_TABLA. Corra 'manage.py leer_smartpss --explorar' "
            "para encontrar el nombre de la tabla que creo SmartPSS."
        )
    if not NOMBRE_VALIDO.match(tabla):
        raise TablaInvalida(
            f"Nombre de tabla invalido: {tabla!r}. Solo letras, numeros, guion bajo "
            "y opcionalmente un punto para calificar la base."
        )
    return tabla


def _entrecomillar(tabla: str) -> str:
    partes = tabla.split(".")
    comilla = '"' if connection.vendor == "sqlite" else "`"
    return ".".join(f"{comilla}{p}{comilla}" for p in partes)


def tablas_candidatas() -> list[str]:
    """Tablas de la base actual que tienen la columna AttendanceUtcTime."""
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            nombres = [f[0] for f in cursor.fetchall()]
            encontradas = []
            for nombre in nombres:
                cursor.execute(f'PRAGMA table_info("{nombre}")')
                columnas = {f[1].lower() for f in cursor.fetchall()}
                if COLUMNA_FIRMA in columnas:
                    encontradas.append(nombre)
            return encontradas

        cursor.execute(
            "SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.COLUMNS "
            "WHERE LOWER(COLUMN_NAME) = %s "
            "AND TABLE_SCHEMA NOT IN "
            "('information_schema', 'mysql', 'performance_schema', 'sys')",
            [COLUMNA_FIRMA],
        )
        filas = cursor.fetchall()

    actual = connection.settings_dict.get("NAME")
    # Si esta en la base actual basta el nombre; si no, hay que calificarlo.
    return [t if b == actual else f"{b}.{t}" for b, t in filas]


def total_de(tabla: str) -> int:
    """Cuantas filas tiene la tabla de SmartPSS."""
    nombre = _entrecomillar(validar_nombre(tabla))
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {nombre}")
        return cursor.fetchone()[0]


def resumen_de(tabla: str) -> dict:
    """Cuantas filas hay, desde cuando y las ultimas tres. Para el modo --explorar."""
    nombre = _entrecomillar(validar_nombre(tabla))
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {nombre}")
        total = cursor.fetchone()[0]
        rango = (None, None)
        muestra = []
        if total:
            cursor.execute(
                f"SELECT MIN({LOCAL_EN_MS}), MAX({LOCAL_EN_MS}) FROM {nombre}"
            )
            menor, mayor = cursor.fetchone()
            rango = (local_ms_a_utc_ms(menor), local_ms_a_utc_ms(mayor))
            cursor.execute(
                f"SELECT {', '.join(COLUMNAS_SELECT)} FROM {nombre} "
                f"ORDER BY {LOCAL_EN_MS} DESC LIMIT 3"
            )
            campos = [c[0] for c in cursor.description]
            muestra = [dict(zip(campos, f)) for f in cursor.fetchall()]
    return {"tabla": tabla, "total": total, "rango": rango, "muestra": muestra}


def leer_desde(tabla: str, utc_ms: int, limite: int) -> list[dict]:
    """Marcas desde ese momento UTC, ya traducidas a lo que espera la ingesta.

    El filtro va sobre AttendanceDateTime porque AttendanceUtcTime puede venir
    en 0, y una marca con 0 nunca pasaria un filtro por fecha.
    """
    nombre = _entrecomillar(validar_nombre(tabla))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {', '.join(COLUMNAS_SELECT)} FROM {nombre} "
            f"WHERE {LOCAL_EN_MS} >= %s ORDER BY {LOCAL_EN_MS} LIMIT %s",
            [utc_ms_a_local_ms(utc_ms), limite],
        )
        campos = [c[0] for c in cursor.description]
        filas = [dict(zip(campos, f)) for f in cursor.fetchall()]
    return [traducir(f) for f in filas]


def traducir(fila: dict) -> dict:
    """De los nombres de SmartPSS a los que espera el servicio de ingesta."""
    return {
        "person_id": str(fila.get("PersonID") or ""),
        "person_name": fila.get("PersonName") or "",
        "card_no": fila.get("PerSonCardNo") or "",
        "utc_ms": utc_ms_de_la_fila(fila),
        "state": int(fila.get("AttendanceState") or 0),
        "method": int(fila.get("AttendanceMethod") or 0),
        "device_ip": fila.get("DeviceIPAddress") or "",
        "device_name": fila.get("DeviceName") or "",
        "snapshot_path": fila.get("SnapshotsPath") or "",
        "handler": fila.get("Handler") or "",
        "remarks": fila.get("Remarks") or "",
    }


def unidad(valor) -> str:
    """13 digitos son milisegundos, 10 son segundos."""
    if valor is None:
        return "?"
    return "ms" if abs(int(valor)) > 10**12 else "s"


def a_segundos(valor) -> int:
    return int(valor) // 1000 if unidad(valor) == "ms" else int(valor)
