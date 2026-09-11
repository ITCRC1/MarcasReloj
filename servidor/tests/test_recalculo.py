"""Recalculo y correcciones."""

from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.core.tiempo import datetime_local
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.marcas.servicio import (
    anular_marca,
    anular_marca_manual,
    crear_marca_manual,
    ingestar,
)
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import recalcular
from tests.conftest import marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


def marcas_de(fecha, *horas, person_id="1024"):
    return [marca_json(person_id, utc_ms_de(fecha, h)) for h in horas]


@pytest.mark.django_db
def test_el_recalculo_es_idempotente(maria):
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    primero = recalcular(maria, LUNES)
    valores = {
        c: getattr(primero, c)
        for c in ("estado", "minutos_ordinarios", "minutos_extra", "minutos_no_laborados")
    }
    segundo = recalcular(maria, LUNES)
    assert primero.pk == segundo.pk
    assert all(getattr(segundo, c) == v for c, v in valores.items())


@pytest.mark.django_db
def test_flujo_olvido_de_salida(maria, usuario):
    """Lo que mas va a pasar: alguien olvida marcar la salida."""
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0)))
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"

    crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido",
        "Salio a las 5:00 pm, lo confirma el guarda.", usuario,
    )

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480
    assert any("manual" in o for o in resultado.observaciones)
    assert MarcaManual.objects.get().creada_por == usuario


@pytest.mark.django_db
def test_anular_una_marca_la_saca_del_calculo_pero_no_de_la_base(maria, usuario):
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    sobrante = MarcaReloj.objects.order_by("fecha_hora")[2]
    assert sobrante.hora_local.strftime("%H:%M") == "13:00"

    anular_marca(sobrante, usuario, "Marco por error al pasar frente al reloj.")

    sobrante.refresh_from_db()
    assert sobrante.anulada is True
    assert sobrante.anulada_por == usuario
    assert MarcaReloj.objects.count() == 4  # sigue existiendo
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"


@pytest.mark.django_db
def test_anular_una_marca_manual_devuelve_el_dia_a_como_estaba(maria, usuario):
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0)))
    manual = crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido", "prueba", usuario
    )
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "OK"

    anular_marca_manual(manual, "Se agrego al empleado equivocado.")

    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"
    assert MarcaManual.objects.count() == 1  # sigue existiendo, anulada


@pytest.mark.django_db
def test_no_se_genera_ausente_para_hoy(maria):
    """Marcar ausente a alguien que quiza aun va a llegar seria un error que
    aparece y desaparece solo."""
    hoy = timezone.localdate()
    recalcular(maria, hoy)
    assert not ResultadoDiario.objects.filter(
        empleado=maria, fecha=hoy, estado="AUSENTE"
    ).exists()


@pytest.mark.django_db
def test_ausente_si_el_dia_ya_paso(maria):
    ayer_habil = timezone.localdate() - timedelta(days=1)
    while ayer_habil.weekday() >= 5:
        ayer_habil -= timedelta(days=1)
    resultado = recalcular(maria, ayer_habil)
    assert resultado.estado == "AUSENTE"
    assert resultado.minutos_no_laborados == resultado.minutos_esperados == 480


@pytest.mark.django_db
def test_no_se_calcula_antes_del_ingreso(maria):
    assert recalcular(maria, date(2023, 6, 1)) is None


@pytest.mark.django_db
def test_un_feriado_trabajado_no_cuenta_como_dia_normal(maria):
    from apps.horarios.models import Feriado

    Feriado.objects.create(fecha=LUNES, nombre="Feriado de prueba")
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    recalcular(maria, LUNES)

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.minutos_ordinarios == 0
    assert resultado.minutos_esperados == 0
    assert resultado.minutos_feriado == 480


# --------------------------------------------------------------------------
# Entrada o salida: el reloj no lo dice, sale de la posicion
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_las_marcas_se_guardan_como_entrada_y_salida_alternadas(maria):
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    filas = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).marcas_usadas
    assert [f["papel"] for f in filas] == ["entrada", "salida", "entrada", "salida"]
    assert not any(f["sin_pareja"] for f in filas)


@pytest.mark.django_db
def test_la_entrada_sin_salida_queda_senalada(maria):
    """Es el caso que hay que poder ver de un vistazo para corregirlo."""
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0)))
    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "INCONSISTENTE"
    sueltas = [f for f in resultado.marcas_usadas if f["sin_pareja"]]
    assert [f["hora"] for f in sueltas] == ["13:00"]


@pytest.mark.django_db
def test_la_marca_manual_que_completa_el_dia_queda_como_salida(maria, usuario):
    ingestar(marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0)))
    crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido", "Lo confirma el guarda.", usuario,
    )
    filas = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).marcas_usadas
    manual = next(f for f in filas if f["origen"] == "manual")
    assert manual["papel"] == "salida"
    assert not any(f["sin_pareja"] for f in filas)


@pytest.mark.django_db
def test_una_marca_descartada_no_tiene_papel(maria):
    """La duplicada no cuenta, asi que no puede aparecer como entrada ni salida."""
    ingestar(marcas_de(LUNES, time(8, 0), time(8, 1), time(12, 0), time(13, 0), time(17, 0)))
    filas = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).marcas_usadas
    descartadas = [f for f in filas if f["descartada_por_duplicado"]]
    assert descartadas and all(f["papel"] == "" for f in descartadas)
    usadas = [f for f in filas if not f["descartada_por_duplicado"]]
    assert [f["papel"] for f in usadas] == ["entrada", "salida", "entrada", "salida"]