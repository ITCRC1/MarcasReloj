"""Los archivos que lee la plataforma de despliegue.

Railway los parsea con Go, que es estricto: un BOM al inicio del archivo tumba el
despliegue con "invalid character 'i' looking for beginning of value", un mensaje
que no dice nada sobre la causa real. PowerShell en Windows escribe UTF-8 con BOM
por defecto, asi que es facil volver a meterlo sin darse cuenta.
"""

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent

ARCHIVOS_DE_DESPLIEGUE = [
    RAIZ / "railway.json",
    RAIZ / "servidor" / "railway.json",
    RAIZ / "Procfile",
    RAIZ / "requirements.txt",
    RAIZ / ".python-version",
]

BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize("ruta", ARCHIVOS_DE_DESPLIEGUE, ids=lambda r: r.name)
def test_no_empiezan_con_bom(ruta):
    assert ruta.exists(), f"falta {ruta}"
    assert not ruta.read_bytes().startswith(BOM), (
        f"{ruta.name} empieza con BOM. Railway no lo va a poder leer. "
        "En PowerShell use [System.IO.File]::WriteAllText con UTF8Encoding($false), "
        "no Out-File -Encoding utf8."
    )


@pytest.mark.parametrize(
    "ruta", [RAIZ / "railway.json", RAIZ / "servidor" / "railway.json"], ids=lambda r: str(r.parent.name)
)
def test_el_railway_json_es_json_valido(ruta):
    configuracion = json.loads(ruta.read_text(encoding="utf-8"))
    assert "deploy" in configuracion
    assert "startCommand" in configuracion["deploy"]


@pytest.mark.parametrize(
    "ruta", [RAIZ / "railway.json", RAIZ / "servidor" / "railway.json"], ids=lambda r: str(r.parent.name)
)
def test_el_healthcheck_apunta_a_una_ruta_que_existe(ruta):
    """Un healthcheck a una ruta borrada deja el despliegue en rojo sin motivo aparente."""
    from django.urls import resolve

    configuracion = json.loads(ruta.read_text(encoding="utf-8"))
    camino = configuracion["deploy"].get("healthcheckPath")
    if camino:
        assert resolve(camino), f"{camino} no resuelve a ninguna vista"


def test_el_procfile_declara_el_proceso_web():
    contenido = (RAIZ / "Procfile").read_text(encoding="utf-8")
    assert contenido.startswith("web:"), (
        "El Procfile debe empezar con 'web:'. Si empieza con un BOM, la plataforma "
        "no reconoce el proceso."
    )
    assert "gunicorn" in contenido
