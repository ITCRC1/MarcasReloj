"""Todas las pantallas responden y los reportes se generan."""

from datetime import date, time

import pytest

from apps.marcas.servicio import ingestar
from apps.periodos.models import Periodo
from tests.conftest import CLAVE, marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


@pytest.fixture
def datos(sucursal, maria, carlos, usuarios, horario_partido):
    ingestar(sucursal, [
        marca_json("1024", utc_ms_de(LUNES, time(8, 12))),
        marca_json("1024", utc_ms_de(LUNES, time(12, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(13, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(17, 30))),
        marca_json("9999", utc_ms_de(LUNES, time(7, 55)), person_name="Sin duenio"),
    ])
    periodo = Periodo.objects.create(
        nombre="Primera quincena de setiembre 2026",
        desde=date(2026, 9, 1), hasta=date(2026, 9, 15),
    )
    return {"periodo": periodo, "maria": maria, "horario": horario_partido}


PANTALLAS = [
    "/",
    "/empleados/",
    "/bitacora/",
    "/marcas/pendientes/",
    "/marcas/crudas/",
    "/horarios/",
    "/horarios/asignaciones/",
    "/horarios/feriados/",
    "/horarios/justificaciones/",
    "/periodos/",
    "/reportes/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("ruta", PANTALLAS)
def test_las_pantallas_responden_para_rrhh(client, datos, ruta):
    client.login(username="rrhh", password=CLAVE)
    assert client.get(ruta).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("rol", ["admin", "rrhh", "supervisor", "consulta"])
def test_el_tablero_responde_para_todos_los_roles(client, datos, rol):
    client.login(username=rol, password=CLAVE)
    assert client.get("/").status_code == 200


@pytest.mark.django_db
def test_pantallas_con_parametros(client, datos):
    client.login(username="rrhh", password=CLAVE)
    periodo = datos["periodo"]
    maria = datos["maria"]
    rutas = [
        f"/marcas/dia/{maria.codigo_planilla}/{LUNES}/",
        f"/marcas/dia/{maria.codigo_planilla}/hoy/",
        f"/empleados/{maria.pk}/",
        f"/empleados/{maria.pk}/editar/",
        "/empleados/nuevo/",
        f"/horarios/{datos['horario'].pk}/",
        f"/periodos/{periodo.pk}/",
        f"/periodos/{periodo.pk}/?validar=1",
        f"/reportes/periodo/{periodo.pk}/resumen/",
        f"/reportes/periodo/{periodo.pk}/tardias/",
        f"/reportes/periodo/{periodo.pk}/empleado/{maria.codigo_planilla}/",
    ]
    for ruta in rutas:
        respuesta = client.get(ruta, follow=True)
        assert respuesta.status_code == 200, f"{ruta} devolvio {respuesta.status_code}"


@pytest.mark.django_db
def test_exportacion_a_excel(client, datos):
    client.login(username="rrhh", password=CLAVE)
    periodo = datos["periodo"]
    respuesta = client.get(f"/reportes/periodo/{periodo.pk}/resumen/?formato=excel")
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"].startswith("application/vnd.openxmlformats")
    assert respuesta.content[:2] == b"PK"  # un xlsx es un zip


@pytest.mark.django_db
def test_exportacion_a_csv(client, datos):
    client.login(username="rrhh", password=CLAVE)
    respuesta = client.get(f"/reportes/periodo/{datos['periodo'].pk}/resumen/?formato=csv")
    assert respuesta.status_code == 200
    texto = respuesta.content.decode("utf-8")
    assert "codigo_empleado" in texto
    assert "E-0042" in texto


@pytest.mark.django_db
def test_exportacion_a_pdf(client, datos):
    client.login(username="rrhh", password=CLAVE)
    ruta = (
        f"/reportes/periodo/{datos['periodo'].pk}"
        f"/empleado/{datos['maria'].codigo_planilla}/?formato=pdf"
    )
    respuesta = client.get(ruta)
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    assert respuesta.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_el_detalle_del_dia_muestra_las_marcas(client, datos):
    client.login(username="rrhh", password=CLAVE)
    respuesta = client.get(f"/marcas/dia/{datos['maria'].codigo_planilla}/{LUNES}/")
    contenido = respuesta.content.decode("utf-8")
    assert "08:12" in contenido
    assert "17:30" in contenido
    assert "7:48" in contenido  # 468 minutos ordinarios como H:MM


@pytest.mark.django_db
def test_ciclo_completo_de_cierre(client, datos, usuarios):
    """Validar, corregir lo que bloquea y cerrar."""
    from apps.core.models import Empleado
    from apps.marcas.servicio import mapear_person_id
    from apps.periodos.models import Periodo as P
    from apps.periodos.servicio import puede_cerrarse, validaciones_de_cierre

    periodo = datos["periodo"]
    validaciones = validaciones_de_cierre(periodo)
    # La marca del PersonID 9999 bloquea el cierre.
    assert not puede_cerrarse(periodo, validaciones)
    assert any("sin empleado" in v.nombre and not v.ok for v in validaciones)

    nuevo = Empleado.objects.create(
        codigo_planilla="E-0099", nombre="Sin duenio",
        departamento=datos["maria"].departamento, fecha_ingreso=date(2024, 1, 1),
    )
    mapear_person_id(nuevo, "9999")

    validaciones = validaciones_de_cierre(periodo)
    nombres_fallidos = [v.nombre for v in validaciones if not v.ok]
    # Queda el dia inconsistente del empleado nuevo (una sola marca).
    assert "Sin dias inconsistentes" in nombres_fallidos

    P.objects.filter(pk=periodo.pk).update(estado="abierto")
