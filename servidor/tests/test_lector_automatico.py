"""El sistema tiene que traer las marcas solo.

Esto se escribio despues de que el reloj estuviera marcando tres dias sin que
llegara nada: SmartPSS escribia bien, la base estaba bien, pero en Railway
nadie corria `leer_smartpss`. El servidor web solo servia paginas.
"""

import pytest
from django.test import override_settings

from apps.marcas import importador, lector_automatico
from apps.marcas.apps import esta_sirviendo
from apps.marcas.models import MarcaReloj
from tests.test_lectura_directa import TABLA, escribir_marca, tabla_smartpss  # noqa: F401

from datetime import date, time

LUNES = date(2026, 9, 7)


# --------------------------------------------------------------------------
# Cuando corresponde leer solo
# --------------------------------------------------------------------------


@override_settings(SMARTPSS_AUTO=True, SMARTPSS_TABLA=TABLA)
def test_con_todo_configurado_debe_leer():
    puede, motivo = lector_automatico.debe_arrancar()
    assert puede and motivo == ""


@override_settings(SMARTPSS_AUTO=False, SMARTPSS_TABLA=TABLA)
def test_apagado_a_proposito_no_lee():
    puede, motivo = lector_automatico.debe_arrancar()
    assert not puede
    assert "SMARTPSS_AUTO" in motivo


@override_settings(SMARTPSS_AUTO=True, SMARTPSS_TABLA="")
def test_sin_tabla_configurada_no_lee_y_dice_por_que():
    """Callarse aqui es lo que dejo el sistema sin marcas sin que nadie lo viera."""
    puede, motivo = lector_automatico.debe_arrancar()
    assert not puede
    assert "SMARTPSS_TABLA" in motivo


def test_no_arranca_durante_las_pruebas():
    """Un hilo leyendo la base de pruebas no tiene sentido y estorba."""
    assert esta_sirviendo() is False


def test_no_arranca_en_un_comando_de_mantenimiento(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "pytest", raising=False)
    for comando in ("migrate", "collectstatic", "shell", "crear_admin"):
        monkeypatch.setattr("sys.argv", ["manage.py", comando])
        assert esta_sirviendo() is False, comando


def test_arranca_bajo_gunicorn(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "pytest", raising=False)
    monkeypatch.setattr("sys.argv", ["/usr/local/bin/gunicorn", "config.wsgi"])
    assert esta_sirviendo() is True


def test_con_runserver_solo_arranca_el_proceso_que_sirve(monkeypatch):
    """Con recarga automatica hay dos procesos; solo uno debe leer."""
    monkeypatch.delitem(__import__("sys").modules, "pytest", raising=False)
    monkeypatch.setattr("sys.argv", ["manage.py", "runserver"])

    monkeypatch.delenv("RUN_MAIN", raising=False)
    assert esta_sirviendo() is False

    monkeypatch.setenv("RUN_MAIN", "true")
    assert esta_sirviendo() is True


# --------------------------------------------------------------------------
# La pasada que corre el hilo es la misma del comando
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_una_pasada_importa_lo_que_haya(tabla_smartpss, maria):  # noqa: F811
    for hora in (time(8, 0), time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora, unidad="s")

    resultado = importador.una_pasada(TABLA)

    assert resultado["nuevas"] == 4
    assert MarcaReloj.objects.count() == 4


@pytest.mark.django_db
def test_dos_pasadas_seguidas_no_duplican(tabla_smartpss, maria):  # noqa: F811
    """El hilo repite cada minuto: releer no puede inflar las horas de nadie."""
    escribir_marca("1024", LUNES, time(8, 0), unidad="s")
    escribir_marca("1024", LUNES, time(17, 0), unidad="s")

    importador.una_pasada(TABLA)
    segunda = importador.una_pasada(TABLA)

    assert segunda["nuevas"] == 0
    assert MarcaReloj.objects.count() == 2


@pytest.mark.django_db
def test_pendientes_cuenta_lo_que_falta_por_importar(tabla_smartpss, maria):  # noqa: F811
    """Es el numero del tablero que delata que la importacion se detuvo."""
    for hora in (time(8, 0), time(12, 0)):
        escribir_marca("1024", LUNES, hora, unidad="s")

    assert importador.pendientes(TABLA) == 2
    importador.una_pasada(TABLA)
    assert importador.pendientes(TABLA) == 0


@pytest.mark.django_db
def test_pendientes_no_revienta_si_la_tabla_no_existe(db):
    """El tablero tiene que abrir aunque la configuracion este mal."""
    assert importador.pendientes("") is None
    assert importador.pendientes("tabla_que_no_existe") is None
