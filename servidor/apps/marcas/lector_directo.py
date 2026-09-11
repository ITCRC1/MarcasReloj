"""Lectura de la tabla de SmartPSS cuando esta en la misma base del sistema.

Cuando SmartPSS escribe directamente en la base de este sistema, el agente sobra:
no hay nada que transportar de una maquina a otra. Este modulo lee esa tabla con
la conexion que ya tiene Django y entrega las marcas al mismo servicio de ingesta
que usa el agente, asi que las reglas de duplicados y de recalculo son identicas.

Sobre la tabla de SmartPSS solo se hace SELECT. Nunca se escribe ni se borra.
"""

import re

from django.db import connection

# Columnas que SmartPSS crea. El orden es el de su documentacion.
COLUMNAS = [
    "PersonID", "PersonName", "PerSonCardNo", "AttendanceUtcTime",
    "AttendanceState", "AttendanceMethod", "DeviceIPAddress", "DeviceName",
    "SnapshotsPath", "Handler", "Remarks",
]

COLUMNA_FIRMA = "attendanceutctime"

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
                f"SELECT MIN(AttendanceUtcTime), MAX(AttendanceUtcTime) FROM {nombre}"
            )
            rango = cursor.fetchone()
            cursor.execute(
                f"SELECT {', '.join(COLUMNAS)}, AttendanceDateTime FROM {nombre} "
                "ORDER BY AttendanceUtcTime DESC LIMIT 3"
            )
            campos = [c[0] for c in cursor.description]
            muestra = [dict(zip(campos, f)) for f in cursor.fetchall()]
    return {"tabla": tabla, "total": total, "rango": rango, "muestra": muestra}


def leer_desde(tabla: str, utc_ms: int, limite: int) -> list[dict]:
    """Marcas con AttendanceUtcTime >= utc_ms, ya traducidas a lo que espera la ingesta."""
    nombre = _entrecomillar(validar_nombre(tabla))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {', '.join(COLUMNAS)} FROM {nombre} "
            "WHERE AttendanceUtcTime >= %s ORDER BY AttendanceUtcTime LIMIT %s",
            [utc_ms, limite],
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
        "utc_ms": int(fila["AttendanceUtcTime"]),
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
