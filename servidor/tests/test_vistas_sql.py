"""Las vistas SQL de la seccion 13.3 entregan lo mismo que la API."""

from datetime import date, time

import pytest
from django.db import connection

from apps.marcas.servicio import ingestar
from apps.motor.servicio import recalcular_rango
from apps.periodos.models import Ajuste, Periodo
from apps.periodos.servicio import resumen_periodo
from tests.conftest import marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


def consultar(sql, *parametros):
    with connection.cursor() as cursor:
        cursor.execute(sql, parametros)
        columnas = [c[0] for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


@pytest.fixture
def periodo_con_datos(sucursal, maria):
    ingestar(sucursal, [
        marca_json("1024", utc_ms_de(LUNES, time(8, 12))),
        marca_json("1024", utc_ms_de(LUNES, time(12, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(13, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(18, 30))),
    ])
    periodo = Periodo.objects.create(
        nombre="Primera quincena de setiembre 2026",
        desde=date(2026, 9, 1), hasta=date(2026, 9, 15),
    )
    recalcular_rango(LUNES, LUNES, [maria])
    return periodo


@pytest.mark.django_db
def test_v_detalle_diario(periodo_con_datos, maria):
    filas = consultar(
        "SELECT * FROM v_detalle_diario WHERE codigo_empleado = %s AND fecha = %s",
        "E-0042", LUNES.isoformat(),
    )
    assert len(filas) == 1
    fila = filas[0]
    assert fila["empleado"] == "Maria Rodriguez"
    assert fila["departamento"] == "Administracion"
    assert fila["sucursal"] == "Oficina Central"
    assert fila["periodo"] == "Primera quincena de setiembre 2026"
    assert fila["estado"] == "OK"
    assert fila["minutos_ordinarios"] == 468
    assert fila["minutos_extra"] == 90
    assert fila["minutos_tardia"] == 12


@pytest.mark.django_db
def test_v_resumen_periodo_coincide_con_el_servicio(periodo_con_datos, maria):
    filas = consultar(
        "SELECT * FROM v_resumen_periodo WHERE periodo_id = %s AND codigo_empleado = %s",
        periodo_con_datos.pk, "E-0042",
    )
    assert len(filas) == 1
    vista = filas[0]

    servicio = next(
        f for f in resumen_periodo(periodo_con_datos)
        if f["codigo_empleado"] == "E-0042"
    )

    # La vista SQL y el servicio de Python deben dar exactamente lo mismo.
    for campo in (
        "minutos_esperados", "minutos_ordinarios", "minutos_extra", "minutos_tardia",
        "minutos_salida_anticipada", "minutos_no_laborados", "minutos_fuera_horario",
        "minutos_feriado", "minutos_descanso_trabajado",
        "dias_laborados", "dias_ausente", "dias_justificados", "dias_feriado",
        "dias_pendientes",
    ):
        assert vista[campo] == servicio[campo], f"difieren en {campo}"


@pytest.mark.django_db
def test_la_vista_de_resumen_suma_los_ajustes(periodo_con_datos, maria, usuarios):
    Ajuste.objects.create(
        empleado=maria, periodo_destino=periodo_con_datos,
        fecha_original=date(2026, 8, 28), concepto="extra", minutos=60,
        motivo="Marca recibida despues del cierre", creado_por=usuarios["admin"],
    )
    fila = consultar(
        "SELECT ajustes_minutos FROM v_resumen_periodo "
        "WHERE periodo_id = %s AND codigo_empleado = %s",
        periodo_con_datos.pk, "E-0042",
    )[0]
    assert fila["ajustes_minutos"] == 60


@pytest.mark.django_db
def test_sin_ajustes_la_columna_es_cero(periodo_con_datos):
    fila = consultar(
        "SELECT ajustes_minutos FROM v_resumen_periodo WHERE periodo_id = %s",
        periodo_con_datos.pk,
    )[0]
    assert fila["ajustes_minutos"] == 0
