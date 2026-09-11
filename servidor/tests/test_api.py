"""Pruebas de la API (seccion 13)."""

import json
from datetime import date, time

import pytest

from apps.marcas.models import MarcaReloj
from apps.motor.servicio import recalcular_rango
from apps.periodos.models import Periodo
from tests.conftest import marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


def cabecera(clave):
    return {"HTTP_X_API_KEY": clave}


@pytest.mark.django_db
def test_salud_no_requiere_clave(client):
    respuesta = client.get("/api/v1/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


@pytest.mark.django_db
def test_sin_clave_no_se_lee_nada(client, cliente_api):
    assert client.get("/api/v1/empleados").status_code == 401
    assert client.get("/api/v1/periodos").status_code == 401


@pytest.mark.django_db
def test_clave_invalida_es_rechazada(client, cliente_api):
    respuesta = client.get("/api/v1/empleados", **cabecera("pl_inventada"))
    assert respuesta.status_code == 401


@pytest.mark.django_db
def test_la_clave_del_agente_no_sirve_para_leer(client, sucursal, cliente_api):
    respuesta = client.get("/api/v1/empleados", **cabecera(sucursal.clave_en_claro))
    assert respuesta.status_code == 401


@pytest.mark.django_db
def test_la_clave_de_planillas_no_sirve_para_ingresar_marcas(client, sucursal, cliente_api):
    respuesta = client.post(
        "/api/v1/ingesta/marcas",
        data=json.dumps({"agente": "oficina-central", "marcas": []}),
        content_type="application/json",
        **cabecera(cliente_api.clave_en_claro),
    )
    assert respuesta.status_code == 401


@pytest.mark.django_db
def test_ingesta_por_http(client, sucursal, maria):
    lote = {
        "agente": "oficina-central",
        "enviado_en": "2026-09-07T14:04:10Z",
        "marcas": [
            marca_json("1024", utc_ms_de(LUNES, time(8, 0))),
            marca_json("1024", utc_ms_de(LUNES, time(12, 0))),
            marca_json("1024", utc_ms_de(LUNES, time(13, 0))),
            marca_json("1024", utc_ms_de(LUNES, time(17, 0))),
        ],
    }
    respuesta = client.post(
        "/api/v1/ingesta/marcas", data=json.dumps(lote),
        content_type="application/json", **cabecera(sucursal.clave_en_claro),
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"recibidas": 4, "nuevas": 4, "duplicadas": 0, "sin_empleado": 0}
    assert MarcaReloj.objects.count() == 4

    # El mismo lote otra vez no crea nada.
    repetido = client.post(
        "/api/v1/ingesta/marcas", data=json.dumps(lote),
        content_type="application/json", **cabecera(sucursal.clave_en_claro),
    )
    assert repetido.json()["nuevas"] == 0


@pytest.mark.django_db
def test_un_agente_no_puede_enviar_como_otro(client, sucursal, maria):
    respuesta = client.post(
        "/api/v1/ingesta/marcas",
        data=json.dumps({"agente": "otra-sucursal", "marcas": []}),
        content_type="application/json", **cabecera(sucursal.clave_en_claro),
    )
    assert respuesta.status_code == 403


@pytest.mark.django_db
def test_resumen_del_periodo(client, sucursal, cliente_api, maria):
    from apps.marcas.servicio import ingestar

    ingestar(sucursal, [
        marca_json("1024", utc_ms_de(LUNES, time(8, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(12, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(13, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(18, 30))),
    ])
    periodo = Periodo.objects.create(
        nombre="Primera quincena de setiembre", desde=date(2026, 9, 1), hasta=date(2026, 9, 15)
    )
    recalcular_rango(date(2026, 9, 7), date(2026, 9, 7), [maria])

    respuesta = client.get(
        f"/api/v1/periodos/{periodo.pk}/resumen", **cabecera(cliente_api.clave_en_claro)
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["periodo"]["estado"] == "abierto"
    fila = next(e for e in datos["empleados"] if e["codigo_empleado"] == "E-0042")
    assert fila["minutos_ordinarios"] == 480
    assert fila["minutos_extra"] == 90
    assert fila["tipo_jornada"] == "diurna"


@pytest.mark.django_db
def test_detalle_por_empleado(client, sucursal, cliente_api, maria):
    from apps.marcas.servicio import ingestar

    ingestar(sucursal, [
        marca_json("1024", utc_ms_de(LUNES, time(8, 12))),
        marca_json("1024", utc_ms_de(LUNES, time(12, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(13, 0))),
        marca_json("1024", utc_ms_de(LUNES, time(17, 0))),
    ])
    periodo = Periodo.objects.create(
        nombre="Quincena", desde=date(2026, 9, 1), hasta=date(2026, 9, 15)
    )
    respuesta = client.get(
        f"/api/v1/periodos/{periodo.pk}/detalle?empleado=E-0042",
        **cabecera(cliente_api.clave_en_claro),
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    dia = next(d for d in datos["dias"] if d["fecha"] == "2026-09-07")
    assert dia["estado"] == "OK"
    assert dia["minutos_ordinarios"] == 468
    assert dia["minutos_tardia"] == 12
    assert dia["minutos_no_laborados"] == 12
    assert [m["hora"] for m in dia["marcas"]] == ["08:12", "12:00", "13:00", "17:00"]


@pytest.mark.django_db
def test_detalle_de_un_empleado_que_no_existe(client, cliente_api):
    periodo = Periodo.objects.create(
        nombre="Quincena", desde=date(2026, 9, 1), hasta=date(2026, 9, 15)
    )
    respuesta = client.get(
        f"/api/v1/periodos/{periodo.pk}/detalle?empleado=E-9999",
        **cabecera(cliente_api.clave_en_claro),
    )
    assert respuesta.status_code == 404


@pytest.mark.django_db
def test_empleados_y_ajustes(client, cliente_api, maria, usuarios):
    from apps.periodos.models import Ajuste

    periodo = Periodo.objects.create(
        nombre="Quincena", desde=date(2026, 9, 1), hasta=date(2026, 9, 15)
    )
    Ajuste.objects.create(
        empleado=maria, periodo_destino=periodo, fecha_original=date(2026, 8, 28),
        concepto="extra", minutos=60, motivo="Marca recibida despues del cierre",
        creado_por=usuarios["admin"],
    )

    empleados = client.get("/api/v1/empleados", **cabecera(cliente_api.clave_en_claro)).json()
    assert empleados[0]["codigo_empleado"] == "E-0042"

    ajustes = client.get(
        f"/api/v1/periodos/{periodo.pk}/ajustes", **cabecera(cliente_api.clave_en_claro)
    ).json()
    assert ajustes[0]["minutos"] == 60
    assert ajustes[0]["fecha_original"] == "2026-08-28"
    assert ajustes[0]["codigo_empleado"] == "E-0042"


@pytest.mark.django_db
def test_documentacion_disponible(client):
    assert client.get("/api/docs").status_code == 200
