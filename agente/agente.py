"""Agente colector de marcas.

Corre como servicio de Windows en la misma PC que SmartPSS Lite. Lee la tabla de
asistencia, envia las marcas al servidor y recuerda donde quedo.

No calcula nada: lee, envia y recuerda. Toda la logica vive en el servidor.

    python agente.py             ciclo normal
    python agente.py --explorar  busca la tabla de asistencia dentro de MySQL
    python agente.py --probar    diagnostico: MySQL, unidades de hora y servidor
    python agente.py --una-vez   un solo ciclo y termina

Debe sobrevivir a caidas de internet, del servidor y de MySQL sin perder marcas
ni cerrarse. Si algo falla, no avanza el estado y reintenta en el siguiente ciclo.
"""

import argparse
import logging
import logging.handlers
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pymysql
from dotenv import load_dotenv

from cliente_api import ClienteAPI, siguiente_espera
from estado import guardar, leer
from lector_smartpss import LectorSmartPSS

CARPETA = Path(__file__).resolve().parent
load_dotenv(CARPETA / ".env")

import os  # noqa: E402  (despues de load_dotenv, a proposito)

log = logging.getLogger("agente")


def configurar_log():
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    archivo = logging.handlers.RotatingFileHandler(
        CARPETA / "agente.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    archivo.setFormatter(formato)
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    logging.basicConfig(level=logging.INFO, handlers=[archivo, consola])


class Config:
    """Todo sale del .env. Ninguna clave vive en el codigo."""

    def __init__(self):
        self.db_host = os.getenv("SMARTPSS_DB_HOST", "127.0.0.1")
        self.db_puerto = os.getenv("SMARTPSS_DB_PORT", "3306")
        self.db_nombre = os.getenv("SMARTPSS_DB_NAME", "")
        self.db_usuario = os.getenv("SMARTPSS_DB_USER", "")
        self.db_clave = os.getenv("SMARTPSS_DB_PASSWORD", "")
        self.tabla = os.getenv("SMARTPSS_TABLA", "")

        self.api_url = os.getenv("API_URL", "http://127.0.0.1:8000")
        self.api_key = os.getenv("API_KEY", "")
        self.nombre = os.getenv("AGENTE_NOMBRE", "oficina-central")

        self.fecha_inicio = os.getenv("FECHA_INICIO", "2026-09-01")
        self.intervalo = int(os.getenv("INTERVALO_SEG", "60"))
        self.ventana_horas = int(os.getenv("VENTANA_RELECTURA_HORAS", "48"))
        self.lote_max = int(os.getenv("LOTE_MAX", "500"))

    def faltantes(self) -> list[str]:
        obligatorios = {
            "SMARTPSS_DB_NAME": self.db_nombre,
            "SMARTPSS_DB_USER": self.db_usuario,
            "SMARTPSS_TABLA": self.tabla,
            "API_KEY": self.api_key,
        }
        return [nombre for nombre, valor in obligatorios.items() if not valor]

    def inicio_utc_ms(self) -> int:
        fecha = datetime.fromisoformat(self.fecha_inicio).replace(tzinfo=timezone.utc)
        return int(fecha.timestamp() * 1000)


def un_ciclo(config: Config, lector: LectorSmartPSS, cliente: ClienteAPI) -> bool:
    """Un ciclo completo. Devuelve True si el servidor confirmo el lote."""
    ultimo = leer(config.inicio_utc_ms())

    # Se relee hacia atras porque la tabla no tiene un ID autoincremental y porque
    # SmartPSS, al volver de estar cerrado, puede escribir marcas con horas pasadas.
    # El servidor descarta los duplicados, asi que reenviar nunca hace dano.
    desde = ultimo - config.ventana_horas * 3600 * 1000

    try:
        marcas = lector.leer_desde(desde, config.lote_max)
    except pymysql.MySQLError as error:
        log.error("No se pudo leer de MySQL: %s", error)
        return False

    respuesta = cliente.enviar(marcas)
    if respuesta is None:
        log.warning("Envio fallido; el estado no avanza. Se reintenta.")
        return False

    log.info(
        "Enviadas %s marca(s): %s nuevas, %s duplicadas, %s sin empleado",
        respuesta["recibidas"], respuesta["nuevas"],
        respuesta["duplicadas"], respuesta["sin_empleado"],
    )

    if marcas:
        mayor = max(m["utc_ms"] for m in marcas)
        if mayor > ultimo:
            guardar(mayor)
    return True


def probar(config: Config, lector: LectorSmartPSS, cliente: ClienteAPI) -> int:
    """Diagnostico de los tres puntos que pueden fallar. Los revisa todos."""
    print(f"Agente:   {config.nombre}")
    print(f"Servidor: {config.api_url}")
    print(f"Tabla:    {config.tabla}")
    fallos = 0

    print()
    print("1. El servidor responde")
    if cliente.esta_vivo():
        print("   OK: /api/v1/salud responde")
    else:
        print("   FALLO: no responde. Revise API_URL y que el servidor este levantado.")
        fallos += 1

    print()
    print("2. La base de SmartPSS")
    try:
        print("   " + lector.comprobar().replace("\n", "\n   "))
    except pymysql.MySQLError as error:
        print(f"   FALLO: {error}")
        print("   Revise SMARTPSS_DB_* y que el usuario tenga SELECT sobre la tabla.")
        fallos += 1

    print()
    print("3. La clave del agente (envio de un lote vacio, que sirve de latido)")
    respuesta = cliente.enviar([])
    if respuesta is None:
        print("   FALLO: el servidor rechazo el latido. Revise API_KEY y AGENTE_NOMBRE.")
        fallos += 1
    else:
        print(f"   OK: {respuesta}")

    print()
    print("Sin problemas." if not fallos else f"{fallos} problema(s) por resolver.")
    return 0 if fallos == 0 else 1


def main() -> int:
    argumentos = argparse.ArgumentParser(description="Agente colector de marcas.")
    argumentos.add_argument(
        "--explorar", action="store_true",
        help="busca la tabla de asistencia en MySQL y muestra que poner en el .env",
    )
    argumentos.add_argument("--probar", action="store_true", help="diagnostico y salir")
    argumentos.add_argument("--una-vez", action="store_true", help="un ciclo y salir")
    opciones = argumentos.parse_args()

    configurar_log()
    config = Config()

    # Explorar es lo primero que se corre, cuando todavia no se sabe el nombre de
    # la tabla. Solo necesita como llegar a MySQL.
    if opciones.explorar:
        from explorador import explorar

        return explorar(
            config.db_host, config.db_puerto, config.db_usuario,
            config.db_clave, config.db_nombre or None,
        )

    faltantes = config.faltantes()
    if faltantes:
        log.error("Faltan variables en agente/.env: %s", ", ".join(faltantes))
        return 2

    lector = LectorSmartPSS(
        config.db_host, config.db_puerto, config.db_nombre,
        config.db_usuario, config.db_clave, config.tabla,
    )
    cliente = ClienteAPI(config.api_url, config.api_key, config.nombre)

    if opciones.probar:
        return probar(config, lector, cliente)

    if opciones.una_vez:
        return 0 if un_ciclo(config, lector, cliente) else 1

    log.info("Agente '%s' iniciado. Intervalo %s s.", config.nombre, config.intervalo)
    espera = config.intervalo
    while True:
        try:
            if un_ciclo(config, lector, cliente):
                espera = config.intervalo
            else:
                espera = siguiente_espera(espera, config.intervalo)
                log.info("Reintento en %s s.", espera)
        except KeyboardInterrupt:
            log.info("Detenido por el usuario.")
            return 0
        except Exception:
            # Pase lo que pase, el agente no se cierra: es un servicio.
            log.exception("Error inesperado en el ciclo; se continua.")
            espera = siguiente_espera(espera, config.intervalo)
        time.sleep(espera)


if __name__ == "__main__":
    sys.exit(main())
