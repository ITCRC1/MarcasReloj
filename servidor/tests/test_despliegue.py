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


def test_el_build_no_exige_base_de_datos():
    """collectstatic corre durante el build, cuando puede no haber DATABASE_URL.

    Se ejecuta de verdad en un proceso aparte, simulando Railway sin la variable.
    Es el escenario exacto que tumbo un despliegue: la comprobacion de
    DATABASE_URL se disparaba al importar los settings y mataba el build, aunque
    collectstatic no toca la base para nada.
    """
    import os
    import subprocess
    import sys as _sys

    entorno = dict(os.environ)
    entorno["RAILWAY_SERVICE_ID"] = "prueba"      # como si corriera en Railway
    for variable in ("DATABASE_URL", "MYSQL_URL", "DATABASE_PUBLIC_URL"):
        entorno.pop(variable, None)

    resultado = subprocess.run(
        [_sys.executable, "manage.py", "collectstatic", "--noinput", "--dry-run"],
        cwd=RAIZ / "servidor", env=entorno, capture_output=True, text=True, timeout=120,
    )
    assert resultado.returncode == 0, (
        "collectstatic fallo sin DATABASE_URL. El build de Railway no va a pasar.\n"
        + resultado.stderr[-1500:]
    )


def test_el_arranque_si_exige_base_de_datos():
    """Al reves: migrate sin DATABASE_URL debe negarse, no caer al SQLite temporal."""
    import os
    import subprocess
    import sys as _sys

    entorno = dict(os.environ)
    entorno["RAILWAY_SERVICE_ID"] = "prueba"
    for variable in ("DATABASE_URL", "MYSQL_URL", "DATABASE_PUBLIC_URL"):
        entorno.pop(variable, None)

    resultado = subprocess.run(
        [_sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=RAIZ / "servidor", env=entorno, capture_output=True, text=True, timeout=120,
    )
    assert resultado.returncode != 0, "migrate deberia negarse sin base de datos"
    assert "Falta DATABASE_URL" in resultado.stderr


def test_el_procfile_declara_el_proceso_web():
    contenido = (RAIZ / "Procfile").read_text(encoding="utf-8")
    assert contenido.startswith("web:"), (
        "El Procfile debe empezar con 'web:'. Si empieza con un BOM, la plataforma "
        "no reconoce el proceso."
    )
    assert "gunicorn" in contenido
