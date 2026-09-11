"""Memoria del agente: hasta donde llego la ultima vez.

Es un archivo JSON diminuto al lado del script. Se escribe de forma atomica
(archivo temporal + reemplazo) para que un corte de luz a media escritura no
deje un estado.json corrupto que obligue a releer todo desde el principio.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVO = Path(__file__).resolve().parent / "estado.json"


def leer(por_defecto_utc_ms: int) -> int:
    """Devuelve el ultimo utc_ms confirmado por el servidor."""
    if not ARCHIVO.exists():
        log.info("No hay estado previo; se empieza en %s", por_defecto_utc_ms)
        return por_defecto_utc_ms
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        return int(datos["ultimo_utc_ms"])
    except (ValueError, KeyError, OSError) as error:
        log.warning("estado.json ilegible (%s); se empieza en %s", error, por_defecto_utc_ms)
        return por_defecto_utc_ms


def guardar(ultimo_utc_ms: int) -> None:
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=ARCHIVO.parent, delete=False, suffix=".tmp"
        ) as archivo:
            json.dump({"ultimo_utc_ms": int(ultimo_utc_ms)}, archivo)
            archivo.flush()
            os.fsync(archivo.fileno())
            temporal = archivo.name
        os.replace(temporal, ARCHIVO)
    except OSError as error:
        log.error("No se pudo guardar el estado: %s", error)
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)
