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
    assert primero == {
        "recibidas": 4, "nuevas": 4, "duplicadas": 0, "sin_empleado": 0, "empleados_creados": 0,
    }

    segundo = ingestar(lote_completo())
    assert segundo["nuevas"] == 0
    assert segundo["duplicadas"] == 4
    assert MarcaReloj.objects.count() == 4


# --------------------------------------------------------------------------
# Los usuarios del reloj son los empleados del sistema
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_un_person_id_nuevo_crea_su_empleado(maria):
    """Nadie tiene que cargar a mano a quien ya esta en el reloj."""
    lote = [marca_json("16", m["utc_ms"], person_name="BRAYAN JORGE SOLANO GUIDO")
            for m in lote_completo()]
    resultado = ingestar(lote)

    assert resultado["empleados_creados"] == 1
    assert resultado["sin_empleado"] == 0
    brayan = Empleado.objects.get(person_id_smartpss="16")
    assert brayan.codigo_planilla == "16"
    assert brayan.nombre == "BRAYAN JORGE SOLANO GUIDO"
    assert brayan.fecha_ingreso == LUNES
    assert brayan.activo and brayan.horario is None
    assert MarcaReloj.objects.filter(empleado=brayan).count() == 4


@pytest.mark.django_db
def test_no_duplica_el_empleado_en_el_siguiente_lote(db):
    ingestar(lote_completo(person_id="16"))
    ingestar([marca_json("16", utc_ms_de(date(2026, 9, 8), time(8, 0)))])
    assert Empleado.objects.filter(person_id_smartpss="16").count() == 1


@pytest.mark.django_db
def test_la_fecha_de_ingreso_es_la_primera_marca_del_lote(db):
    lote = [
        marca_json("16", utc_ms_de(date(2026, 9, 10), time(8, 0))),
        marca_json("16", utc_ms_de(date(2026, 8, 12), time(8, 0))),
    ]
    ingestar(lote)
    assert Empleado.objects.get(person_id_smartpss="16").fecha_ingreso == date(2026, 8, 12)


@pytest.mark.django_db
def test_si_el_codigo_ya_lo_usa_otro_empleado_no_falla(db):
    Empleado.objects.create(codigo_planilla="16", nombre="Creado a mano", fecha_ingreso=LUNES)
    ingestar(lote_completo(person_id="16"))
    nuevo = Empleado.objects.get(person_id_smartpss="16")
    assert nuevo.codigo_planilla == "SMARTPSS-16"
    assert MarcaReloj.objects.filter(empleado=nuevo).count() == 4


@pytest.mark.django_db
def test_las_marcas_viejas_sin_empleado_se_adoptan(db):
    """Las 3.359 marcas importadas antes de este cambio quedaron sin dueno."""
    from apps.marcas.servicio import adoptar_marcas_sin_empleado

    ingestar(lote_completo(person_id="16"))
    MarcaReloj.objects.update(empleado=None)
    Empleado.objects.all().delete()

    assert adoptar_marcas_sin_empleado() == 1
    assert MarcaReloj.objects.filter(empleado__isnull=True).count() == 0
    assert adoptar_marcas_sin_empleado() == 0


@pytest.mark.django_db
def test_sin_horario_no_se_calculan_advertencias(db):
    """Sin horario, cada dia salia como 'trabajo en dia libre' y llenaba el tablero."""
    ingestar(lote_completo(person_id="16"))
    assert ResultadoDiario.objects.count() == 0


@pytest.mark.django_db
def test_al_asignar_horario_se_calculan_sus_dias(db, horario_partido):
    from apps.motor.servicio import recalcular_empleado

    ingestar(lote_completo(person_id="16"))
    brayan = Empleado.objects.get(person_id_smartpss="16")
    brayan.horario = horario_partido
    brayan.save()

    recalcular_empleado(brayan)

    resultado = ResultadoDiario.objects.get(empleado=brayan, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480


@pytest.mark.django_db
def test_mapear_adopta_las_marcas_y_recalcula(maria, horario_partido):
    ingestar(lote_completo(person_id="9999"))
    # Marcas que quedaron sin dueno (como antes de crear empleados solos).
    MarcaReloj.objects.filter(person_id="9999").update(empleado=None)
    Empleado.objects.filter(person_id_smartpss="9999").delete()
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
    empleado = Empleado.objects.create(
        codigo_planilla="E-0001", nombre="Sin horario",
        person_id_smartpss="5555", fecha_ingreso=date(2024, 1, 1),
    )
    ingestar(lote_completo(person_id="5555"))
    assert MarcaReloj.objects.filter(empleado=empleado).count() == 4
    assert not ResultadoDiario.objects.exists()
