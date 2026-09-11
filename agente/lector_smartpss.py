"""Lectura de la tabla de asistencia de SmartPSS.

Regla que no se rompe nunca: aqui solo se hace SELECT. El agente usa un usuario
de MySQL que unicamente tiene ese permiso, asi que aunque el codigo se equivoque,
la base de SmartPSS no se puede tocar.
"""

import logging

import pymysql

log = logging.getLogger(__name__)

COLUMNAS = [
    "PersonID", "PersonName", "PerSonCardNo", "AttendanceUtcTime",
    "AttendanceState", "AttendanceMethod", "DeviceIPAddress", "DeviceName",
    "SnapshotsPath", "Handler", "Remarks",
]


class LectorSmartPSS:
    def __init__(self, host, puerto, base, usuario, clave, tabla):
        self.conexion_args = {
            "host": host,
            "port": int(puerto),
            "db": base,
            "user": usuario,
            "password": clave,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": 10,
            "read_timeout": 30,
        }
        # El nombre de la tabla no puede ir parametrizado, asi que se valida.
        if not tabla or not tabla.replace("_", "").isalnum():
            raise ValueError(f"Nombre de tabla invalido: {tabla!r}")
        self.tabla = tabla

    def leer_desde(self, utc_ms: int, limite: int) -> list[dict]:
        """Marcas con AttendanceUtcTime >= utc_ms, ordenadas por hora."""
        consulta = (
            f"SELECT {', '.join(COLUMNAS)} FROM {self.tabla} "
            "WHERE AttendanceUtcTime >= %s ORDER BY AttendanceUtcTime LIMIT %s"
        )
        with pymysql.connect(**self.conexion_args) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(consulta, (utc_ms, limite))
                filas = cursor.fetchall()
        log.debug("Leidas %s fila(s) desde utc_ms=%s", len(filas), utc_ms)
        return [self._traducir(f) for f in filas]

    @staticmethod
    def _traducir(fila: dict) -> dict:
        """De los nombres de SmartPSS a los que espera la API."""
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

    def comprobar(self) -> str:
        """Diagnostico de arranque: cuenta filas y revisa las unidades de tiempo.

        La especificacion pide verificar la diferencia entre AttendanceUtcTime y
        AttendanceDateTime. Solo tiene sentido si ambos estan en la misma unidad,
        asi que primero se mira la magnitud. Ver docs/decisiones-abiertas.md, punto 7.
        """
        with pymysql.connect(**self.conexion_args) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS n FROM {self.tabla}")
                total = cursor.fetchone()["n"]
                cursor.execute(
                    f"SELECT AttendanceUtcTime, AttendanceDateTime FROM {self.tabla} "
                    "ORDER BY AttendanceUtcTime DESC LIMIT 1"
                )
                fila = cursor.fetchone()

        if not fila:
            return f"Tabla {self.tabla}: {total} fila(s). Sin datos para comprobar la hora."

        utc = int(fila["AttendanceUtcTime"])
        local = int(fila["AttendanceDateTime"] or 0)
        unidad_utc = "ms" if utc > 10**12 else "s"
        unidad_local = "ms" if local > 10**12 else "s"
        utc_s = utc // 1000 if unidad_utc == "ms" else utc
        local_s = local // 1000 if unidad_local == "ms" else local
        diferencia = utc_s - local_s
        ok = "correcto" if diferencia == 21600 else f"INESPERADO (se esperaban 21600 s)"
        return (
            f"Tabla {self.tabla}: {total} fila(s).\n"
            f"  AttendanceUtcTime={utc} ({unidad_utc}), "
            f"AttendanceDateTime={local} ({unidad_local})\n"
            f"  Diferencia: {diferencia} s -> {ok}"
        )
