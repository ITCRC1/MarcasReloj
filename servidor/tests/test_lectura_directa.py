"""Lectura directa: SmartPSS escribe en esta misma base y el sistema la lee.

Se crea una tabla identica a la que crea SmartPSS (las 12 columnas de su
documentacion), se le insertan marcas y se comprueba que el comando las importe,
las mapee al empleado y calcule el dia, sin agente de por medio.
"""

from datetime import date, time, timedelta

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
    """Como escribiria SmartPSS: AttendanceDateTime es la hora local como epoch.

    La unidad de AttendanceUtcTime cambia segun la instalacion de SmartPSS: unas
    escriben milisegundos y otras segundos. Por eso se puede elegir con
    unidad="s", que es lo que manda el reloj del comedor. Con unidad="cero" se
    escribe como SmartPSS sube el historial: AttendanceUtcTime en 0.
    """
    utc_ms = utc_ms_de(fecha, hora)
    unidad = extra.get("unidad", "ms")
    utc = {"ms": utc_ms, "s": utc_ms // 1000, "cero": 0}[unidad]
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
            utc,
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
@pytest.mark.parametrize("unidad", ["ms", "s"])
def test_la_hora_sale_de_utc_ms(tabla_smartpss, maria, unidad):
    """La hora debe salir igual escriba SmartPSS segundos o milisegundos.

    El reloj del comedor escribe segundos. Leer ese valor como milisegundos
    mandaba la marca a enero de 1970 y el dia nunca se calculaba.
    """
    escribir_marca("1024", LUNES, time(8, 0), unidad=unidad)
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    marca = MarcaReloj.objects.get()
    assert marca.fecha_local == LUNES
    assert marca.hora_local.strftime("%H:%M") == "08:00"


@pytest.mark.django_db
def test_un_dia_completo_en_segundos_se_calcula_igual(tabla_smartpss, maria):
    for hora in (time(8, 12), time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora, unidad="s")

    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 468
    assert resultado.minutos_tardia == 12


@pytest.mark.django_db
def test_la_marca_anterior_no_se_vuelve_a_traer_con_segundos(tabla_smartpss, maria):
    """La marca de agua se guarda en milisegundos; la tabla esta en segundos."""
    for hora in (time(8, 0), time(12, 0), time(13, 0), time(17, 0)):
        escribir_marca("1024", LUNES, hora, unidad="s")

    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    assert MarcaReloj.objects.count() == 4


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


# --------------------------------------------------------------------------
# AttendanceUtcTime en 0: como SmartPSS sube el historial
# --------------------------------------------------------------------------


def test_la_hora_local_de_smartpss_se_convierte_bien_con_un_valor_real():
    """Valores de la primera marca real: las dos columnas tienen que coincidir."""
    assert lector_directo.local_ms_a_utc_ms(1789161884000) == 1789183484000
    assert lector_directo.utc_ms_a_local_ms(1789183484000) == 1789161884000


@pytest.mark.django_db
def test_una_marca_con_utc_en_cero_toma_la_hora_de_attendance_datetime(tabla_smartpss, maria):
    """2.917 de las primeras 3.218 marcas reales llegaron asi y se perdian."""
    escribir_marca("1024", LUNES, time(8, 0), unidad="cero")
    call_command("leer_smartpss", tabla=TABLA, verbosity=0)
    marca = MarcaReloj.objects.get()
    assert marca.fecha_local == LUNES
    assert marca.hora_local.strftime("%H:%M") == "08:00"


@pytest.mark.django_db
def test_un_dia_con_marcas_mezcladas_se_calcula_completo(tabla_smartpss, maria):
    """El 11 de setiembre llegaron marcas con UtcTime y sin UtcTime el mismo dia."""
    escribir_marca("1024", LUNES, time(8, 12), unidad="cero")
    escribir_marca("1024", LUNES, time(12, 0), unidad="cero")
    escribir_marca("1024", LUNES, time(13, 0), unidad="s")
    escribir_marca("1024", LUNES, time(17, 0), unidad="s")

    call_command("leer_smartpss", tabla=TABLA, verbosity=0)

    resultado = ResultadoDiario.objects.get(empleado=maria, fecha=LUNES)
    assert resultado.estado == "OK"
    assert resultado.minutos_ordinarios == 468


@pytest.mark.django_db
def test_la_misma_marca_con_y_sin_utc_no_se_duplica(tabla_smartpss, maria):
    """Derivar la hora de una u otra columna tiene que dar la misma llave."""
    from apps.marcas.servicio import ingestar

    fila = {"PersonID": "1024", "AttendanceDateTime": utc_ms_de(LUNES, time(8, 0)) - 6 * 3600 * 1000,
            "AttendanceUtcTime": 0, "DeviceIPAddress": "X"}
    con_utc = dict(fila, AttendanceUtcTime=utc_ms_de(LUNES, time(8, 0)))
    ingestar([lector_directo.traducir(fila), lector_directo.traducir(con_utc)])
    assert MarcaReloj.objects.count() == 1


@pytest.mark.django_db
def test_lee_todo_aunque_no_quepa_en_un_lote(tabla_smartpss, maria, monkeypatch):
    """La primera vez llegaron mas de 3.000 marcas; el lote era de 2.000."""
    from apps.marcas import importador

    monkeypatch.setattr(importador, "LOTE_MAX", 3)
    for dia in range(5):
        for hora in (time(8, 0), time(12, 0), time(13, 0), time(17, 0)):
            escribir_marca("1024", LUNES + timedelta(days=dia), hora, unidad="cero")

    importador.una_pasada(TABLA)

    assert MarcaReloj.objects.count() == 20


@pytest.mark.django_db
def test_ponerse_al_dia_recupera_marcas_mas_viejas_que_la_ventana(tabla_smartpss, maria):
    """SmartPSS subio historial de un mes; la pasada normal solo mira 48 horas."""
    from apps.marcas import importador

    escribir_marca("1024", LUNES, time(8, 0), unidad="s")
    importador.una_pasada(TABLA)

    # Llega historial de hace un mes, cuando el sistema ya tenia marcas nuevas.
    escribir_marca("1024", LUNES - timedelta(days=30), time(8, 0), unidad="cero")
    importador.una_pasada(TABLA)
    assert importador.pendientes(TABLA) == 1

    importador.ponerse_al_dia(TABLA)
    assert importador.pendientes(TABLA) == 0
    assert MarcaReloj.objects.filter(fecha_local=LUNES - timedelta(days=30)).exists()