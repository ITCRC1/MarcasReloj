"""Ingesta de marcas: duplicados, mapeo y calculo."""

from datetime import date, time

import pytest

from apps.core.models import Empleado
from apps.marcas.models import MarcaReloj
from apps.marcas.servicio import ingestar, mapear_person_id
from apps.motor.models import ResultadoDiario
from tests.conftest import marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


def lote_completo(person_id="1024"):
    return [
        marca_json(person_id, utc_ms_de(LUNES, time(8, 0))),
        marca_json(person_id, utc_ms_de(LUNES, time(12, 0))),
        marca_json(person_id, utc_ms_de(LUNES, time(13, 0))),
        marca_json(person_id, utc_ms_de(LUNES, time(17, 0))),
    ]


@pytest.mark.django_db
def test_reenviar_el_mismo_lote_no_duplica(maria):
    primero = ingestar(lote_completo())
    assert primero == {"recibidas": 4, "nuevas": 4, "duplicadas": 0, "sin_empleado": 0}

    segundo = ingestar(lote_completo())
    assert segundo["nuevas"] == 0
    assert segundo["duplicadas"] == 4
    assert MarcaReloj.objects.count() == 4


@pytest.mark.django_db
def test_person_id_sin_mapear_queda_sin_empleado(maria):
    resultado = ingestar(lote_completo(person_id="9999"))
    assert resultado["sin_empleado"] == 4
    assert MarcaReloj.objects.filter(empleado__isnull=True).count() == 4


@pytest.mark.django_db
def test_mapear_adopta_las_marcas_y_recalcula(maria, horario_partido):
    ingestar(lote_completo(person_id="9999"))
    nuevo = Empleado.objects.create(
        codigo_planilla="E-0099", nombre="Rodrigo Nunez",
        horario=horario_partido, fecha_ingreso=date(2024, 1, 1),
    )

    adoptadas = mapear_person_id(nuevo, "9999")

    assert adoptadas == 4
    assert MarcaReloj.objects.filter(empleado__isnull=True).count() == 0
    resultado = ResultadoDiario.objects.get(empleado=nuevo, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480


@pytest.mark.django_db
def test_la_ingesta_calcula_el_dia(maria):
    ingestar(lote_completo())
    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480
    assert resultado.minutos_no_laborados == 0


@pytest.mark.django_db
def test_la_hora_se_toma_de_utc_ms(maria):
    """utc_ms es la fuente de verdad; la fecha local sale de convertirla a Costa Rica."""
    ingestar([marca_json("1024", utc_ms_de(LUNES, time(8, 0)))])
    marca = MarcaReloj.objects.get()
    assert marca.fecha_local == LUNES
    assert marca.hora_local.strftime("%H:%M") == "08:00"
    # 08:00 en Costa Rica son las 14:00 UTC.
    assert marca.fecha_hora.strftime("%H:%M") == "14:00"


@pytest.mark.django_db
def test_un_empleado_sin_horario_no_rompe_nada(db):
    Empleado.objects.create(
        codigo_planilla="E-0001", nombre="Sin horario",
        person_id_smartpss="5555", fecha_ingreso=date(2024, 1, 1),
    )
    ingestar(lote_completo(person_id="5555"))
    resultado = ResultadoDiario.objects.get(fecha=LUNES)
    # Sin horario todos los dias son libres: lo trabajado va a descanso.
    assert resultado.estado == "ADVERTENCIA"
    assert resultado.minutos_esperados == 0
    assert resultado.minutos_descanso_trabajado == 480
