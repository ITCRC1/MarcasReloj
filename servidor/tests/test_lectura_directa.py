"""Lectura directa: SmartPSS escribe en esta misma base y el sistema la lee.

Se crea una tabla identica a la que crea SmartPSS (las 12 columnas de su
documentacion), se le insertan marcas y se comprueba que el comando las importe,
las mapee al empleado y calcule el dia, sin agente de por medio.
"""

from datetime import date, time

import pytest
from django.core.management import call_command
from django.db import connection

from apps.marcas import lector_directo
from apps.marcas.models import MarcaReloj
from apps.motor.models import ResultadoDiario
from tests.conftest import utc_ms_de

LUNES = date(2026, 9, 7)
TABLA = "tabla_asistencia"

CREAR = f"""
CREATE TABLE {TABLA} (
    PersonID           varchar(30),
    PersonName         varchar(36),
    PerSonCardNo       varchar(20),
    AttendanceDateTime bigint,
    AttendanceState    int,
    AttendanceMethod   int,
    DeviceIPAddress    varchar(20),
    DeviceName         varchar(50),
    SnapshotsPath      varchar(200),
    Handler            varchar(50),
    AttendanceUtcTime  bigint,
    Remarks            varchar(256)
)
"""

INSERTAR = f"""
INSERT INTO {TABLA} (
    PersonID, PersonName, PerSonCardNo, AttendanceDateTime, AttendanceState,
    AttendanceMethod, DeviceIPAddress, DeviceName, SnapshotsPath, Handler,
    AttendanceUtcTime, Remarks
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def escribir_marca(person_id: str, fecha: date, hora: time, **extra):
    """Como escribiria SmartPSS: AttendanceDateTime es la hora local como epoch."""
    utc_ms = utc_ms_de(fecha, hora)
    with connection.cursor() as cursor:
        cursor.execute(INSERTAR, [
            person_id,
            extra.get("nombre", "Maria Rodriguez"),
            "",
            utc_ms - 6 * 3600 * 1000,   # local disfrazada de epoch: 6 horas menos
            0,
            extra.get("metodo", 3),
            "192.168.1.201",
            "Reloj Entrada",
            "",
            extra.get("handler", ""),
            utc_ms,
            "",
        ])


@pytest.fixture
def tabla_smartpss(db):
    with connection.cursor() as cursor:
        cursor.execute(CREAR)
    yield TABLA
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE {TABLA}")


@pytest.mark.django_db
def test_encuentra_la_tabla_de_smartpss(tabla_smartpss):
    assert TABLA in lector_directo.tablas_candidatas()


@pytest.mark.django_db
def test_no_confunde_las_tablas_del_sistema(tabla_smartpss):
    """Solo las que tienen AttendanceUtcTime, no las de Django."""
    candidatas = lector_directo.tablas_candidatas()
    assert "marcas_marcareloj" not in candidatas
    assert "core_empleado" not in candidatas
    assert candidatas == [TABLA]


@pytest.mark.django_db
def test_importa_las_marcas_y_calcula_el_dia(tabla_smartpss, maria):
    for hora in (time(8, 12), time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora)

    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    assert MarcaReloj.objects.count() == 4
    assert MarcaReloj.objects.filter(empleado=maria).count() == 4
    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 468
    assert resultado.minutos_tardia == 12


@pytest.mark.django_db
def test_correr_dos_veces_no_duplica(tabla_smartpss, maria):
    for hora in (time(8, 0), time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora)

    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    assert MarcaReloj.objects.count() == 4


@pytest.mark.django_db
def test_una_marca_nueva_se_agrega_y_recalcula(tabla_smartpss, maria):
    for hora in (time(8, 0), time(12, 0), time(13, 0)):
        escribir_marca("1024", LUNES, hora)
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    assert ResultadoDiario.objects.get(empleado=maria, fecha=LUNES).estado == "INCONSISTENTE"

    # Alguien marca la salida y SmartPSS la escribe.
    escribir_marca("1024", LUNES, time(17, 0))
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 480


@pytest.mark.django_db
def test_un_person_id_sin_mapear_queda_sin_empleado(tabla_smartpss, maria):
    escribir_marca("9999", LUNES, time(8, 0), nombre="Rodrigo Nunez")
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    marca = MarcaReloj.objects.get()
    assert marca.empleado is None
    assert marca.person_name == "Rodrigo Nunez"


@pytest.mark.django_db
def test_la_hora_sale_de_utc_ms(tabla_smartpss, maria):
    escribir_marca("1024", LUNES, time(8, 0))
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    marca = MarcaReloj.objects.get()
    assert marca.fecha_local == LUNES
    assert marca.hora_local.strftime("%H:%M") == "08:00"


@pytest.mark.django_db
def test_el_handler_de_smartpss_llega_hasta_la_observacion(tabla_smartpss, maria):
    escribir_marca("1024", LUNES, time(8, 0), handler="operador1")
    for hora in (time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora)
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert any("SmartPSS" in o for o in resultado.observaciones)


@pytest.mark.django_db
def test_no_se_acepta_un_nombre_de_tabla_peligroso(db):
    for malo in ("tabla; DROP TABLE core_empleado", "tabla--", "a.b.c", ""):
        with pytest.raises(lector_directo.TablaInvalida):
            lector_directo.validar_nombre(malo)


@pytest.mark.django_db
def test_el_comando_avisa_si_no_hay_tabla_configurada(db, maria):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="SMARTPSS_TABLA"):
        call_command("leer_smartpss", verbosity=0)

