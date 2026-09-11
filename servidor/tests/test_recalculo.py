"""Pruebas del servicio de recalculo (secciones 7.8, 8 y 9)."""

from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.marcas.models import MarcaManual, MarcaReloj
from apps.marcas.servicio import (
    PeriodoCerrado,
    aceptar_advertencia,
    anular_marca,
    crear_marca_manual,
    ingestar,
    resolver_marca_manual,
)
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import recalcular
from apps.periodos.models import Periodo
from tests.conftest import marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


def marcas_de(fecha, *horas, person_id="1024"):
    return [marca_json(person_id, utc_ms_de(fecha, h)) for h in horas]


@pytest.mark.django_db
def test_el_recalculo_es_idempotente(sucursal, maria):
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    primero = recalcular(maria, LUNES)
    valores = {
        c: getattr(primero, c)
        for c in ("estado", "minutos_ordinarios", "minutos_extra", "minutos_no_laborados")
    }
    segundo = recalcular(maria, LUNES)
    assert primero.pk == segundo.pk
    assert all(getattr(segundo, c) == v for c, v in valores.items())


@pytest.mark.django_db
def test_una_marca_de_un_periodo_cerrado_no_cambia_el_resultado(sucursal, maria, usuarios):
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    antes = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert antes.minutos_ordinarios == 480

    periodo = Periodo.objects.create(
        nombre="Quincena", desde=date(2026, 9, 1), hasta=date(2026, 9, 15),
        estado="cerrado", cerrado_por=usuarios["admin"], cerrado_en=timezone.now(),
    )

    # Llega tarde una marca mas: se guarda, pero el dia ya no se recalcula.
    resultado = ingestar(sucursal, marcas_de(LUNES, time(18, 30)))
    assert resultado["nuevas"] == 1

    despues = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert despues.minutos_ordinarios == 480
    assert despues.minutos_extra == 0
    assert recalcular(maria, LUNES) is None
    assert periodo.estado == "cerrado"


@pytest.mark.django_db
def test_no_se_corrige_dentro_de_un_periodo_cerrado(sucursal, maria, usuarios):
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(12, 0)))
    Periodo.objects.create(
        nombre="Quincena", desde=date(2026, 9, 1), hasta=date(2026, 9, 15),
        estado="cerrado", cerrado_por=usuarios["admin"], cerrado_en=timezone.now(),
    )
    from apps.core.tiempo import datetime_local

    with pytest.raises(PeriodoCerrado):
        crear_marca_manual(
            maria, datetime_local(LUNES, time(17, 0)), "olvido", "prueba",
            usuarios["rrhh"], aprobada_directamente=True,
        )
    with pytest.raises(PeriodoCerrado):
        anular_marca(MarcaReloj.objects.first(), usuarios["rrhh"], "prueba")


@pytest.mark.django_db
def test_flujo_olvido_de_salida(sucursal, maria, usuarios):
    """El flujo completo de la seccion 8, con dos usuarios distintos."""
    from apps.core.tiempo import datetime_local

    # 1. Tres marcas: el dia queda inconsistente.
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0)))
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"

    # 2. El supervisor agrega la salida: queda pendiente y el dia no cambia.
    manual = crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido",
        "Salio a las 5:00 pm, lo confirma el guarda.",
        usuarios["supervisor"], aprobada_directamente=False,
    )
    assert manual.estado == "pendiente"
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"

    # 3. RRHH la aprueba y el dia se recalcula solo.
    resolver_marca_manual(manual, usuarios["rrhh"], "aprobada")
    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480
    assert any("manual" in o for o in resultado.observaciones)
    manual.refresh_from_db()
    assert manual.creada_por == usuarios["supervisor"]
    assert manual.resuelta_por == usuarios["rrhh"]


@pytest.mark.django_db
def test_anular_una_marca_la_saca_del_calculo_pero_no_de_la_base(sucursal, maria, usuarios):
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(12, 0), time(13, 0), time(17, 0)))
    sobrante = MarcaReloj.objects.order_by("fecha_hora")[2]  # la entrada de las 13:00
    assert sobrante.hora_local.strftime("%H:%M") == "13:00"

    anular_marca(sobrante, usuarios["rrhh"], "Marco por error al pasar frente al reloj.")

    sobrante.refresh_from_db()
    assert sobrante.anulada is True
    assert MarcaReloj.objects.count() == 4  # sigue existiendo
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"


@pytest.mark.django_db
def test_la_aceptacion_se_pierde_si_el_dia_cambia(sucursal, maria, usuarios):
    # Dos marcas en horario partido: advertencia.
    ingestar(sucursal, marcas_de(LUNES, time(8, 0), time(17, 0)))
    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "ADVERTENCIA"

    aceptar_advertencia(resultado, usuarios["rrhh"], "Revisado con el supervisor.")
    resultado.refresh_from_db()
    assert resultado.aceptado is True

    # Llega una marca que cambia los minutos: vuelve a pendientes.
    ingestar(sucursal, marcas_de(LUNES, time(18, 30)))
    resultado.refresh_from_db()
    assert resultado.aceptado is False


@pytest.mark.django_db
def test_no_se_genera_ausente_para_hoy(maria):
    hoy = timezone.localdate()
    assert recalcular(maria, hoy) is None or ResultadoDiario.objects.filter(
        empleado=maria, fecha=hoy, estado="AUSENTE"
    ).count() == 0


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
def test_el_horario_vigente_manda_aunque_despues_cambie(sucursal, maria, horario_partido):
    """Recalcular un dia viejo usa el horario que el empleado tenia entonces."""
    from datetime import time as t

    from apps.horarios.models import AsignacionHorario, BloqueHorario, Horario

    ingestar(sucursal, marcas_de(LUNES, t(8, 0), t(12, 0), t(13, 0), t(17, 0)))
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).minutos_esperados == 480

    # Desde manana tiene otro horario, mas corto.
    corto = Horario.objects.create(nombre="Medio tiempo")
    for dia in range(5):
        BloqueHorario.objects.create(
            horario=corto, dia_semana=dia, orden=1,
            hora_entrada=t(8, 0), hora_salida=t(12, 0))
    maria.asignaciones.update(vigente_hasta=LUNES)
    AsignacionHorario.objects.create(
        empleado=maria, horario=corto, vigente_desde=LUNES + timedelta(days=1)
    )

    recalcular(maria, LUNES)
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).minutos_esperados == 480
