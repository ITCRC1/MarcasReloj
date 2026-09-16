"""API para el sistema de planillas: misma informacion que el reporte, en JSON."""

from datetime import date, time

import pytest
from django.test import override_settings

from apps.core.tiempo import datetime_local
from apps.marcas.servicio import crear_marca_manual, ingestar
from tests.conftest import marca_json, utc_ms_de

CLAVE = "clave-de-prueba-para-planillas"
MARTES = date(2026, 9, 15)
RANGO = {"desde": "2026-09-15", "hasta": "2026-09-15"}


def marcar(person_id, nombre, fecha, *horas):
    ingestar([marca_json(person_id, utc_ms_de(fecha, h), person_name=nombre) for h in horas])


@pytest.fixture
def api(client):
    def get(ruta, params=None, clave=CLAVE):
        encabezados = {"HTTP_AUTHORIZATION": f"Bearer {clave}"} if clave else {}
        with override_settings(API_TOKEN=CLAVE):
            return client.get(f"/api/v1/{ruta}", params or {}, **encabezados)
    return get


@pytest.fixture
def con_marcas(db):
    marcar("14", "BENJAMIN QUIROS MORA", MARTES, time(5, 45), time(14, 5), time(16, 30), time(20, 26))
    marcar("16", "BRAYAN JORGE SOLANO GUIDO", MARTES, time(5, 49))


# --------------------------------------------------------------------------
# Acceso
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_sin_clave_no_entra(api):
    assert api("resumen", RANGO, clave=None).status_code == 401


@pytest.mark.django_db
def test_con_clave_equivocada_no_entra(api):
    assert api("resumen", RANGO, clave="otra").status_code == 401


@pytest.mark.django_db
@override_settings(API_TOKEN="")
def test_sin_api_token_configurado_la_api_esta_cerrada(client):
    r = client.get("/api/v1/resumen", RANGO, HTTP_AUTHORIZATION="Bearer ")
    assert r.status_code == 503


@pytest.mark.django_db
def test_no_acepta_escribir(api, client):
    with override_settings(API_TOKEN=CLAVE):
        r = client.post("/api/v1/resumen", RANGO, HTTP_AUTHORIZATION=f"Bearer {CLAVE}")
    assert r.status_code == 405


@pytest.mark.django_db
@pytest.mark.parametrize("params, texto", [
    ({}, "Faltan"),
    ({"desde": "15/09/2026", "hasta": "2026-09-15"}, "AAAA-MM-DD"),
    ({"desde": "2026-09-15", "hasta": "2026-09-01"}, "anterior"),
    ({"desde": "2026-01-01", "hasta": "2026-09-15"}, "maximo"),
])
def test_el_rango_se_valida_con_un_mensaje_claro(api, params, texto):
    r = api("resumen", params)
    assert r.status_code == 400
    assert texto in r.json()["error"]


# --------------------------------------------------------------------------
# Contenido
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_resumen_por_persona(api, con_marcas):
    datos = api("resumen", RANGO).json()
    por_id = {p["person_id"]: p for p in datos["personas"]}

    assert por_id["14"]["nombre"] == "BENJAMIN QUIROS MORA"
    assert por_id["14"]["total_trabajado"] == {"minutos": 736, "texto": "12:16"}
    assert por_id["14"]["dias_incompletos"] == 0

    assert por_id["16"]["total_trabajado"]["minutos"] == 0
    assert por_id["16"]["fechas_incompletas"] == ["2026-09-15"]


@pytest.mark.django_db
def test_asistencia_dia_por_dia_con_entradas_y_salidas(api, con_marcas):
    datos = api("asistencia", {**RANGO, "person_id": "14"}).json()
    assert datos["zona_horaria"] == "America/Costa_Rica"
    [persona] = datos["personas"]
    [dia] = persona["dias"]

    assert dia["fecha"] == "2026-09-15"
    assert [(m["tipo"], m["hora"]) for m in dia["marcas"]] == [
        ("entrada", "05:45"), ("salida", "14:05"), ("entrada", "16:30"), ("salida", "20:26"),
    ]
    assert dia["tramos"] == [
        {"entrada": "05:45", "salida": "14:05"}, {"entrada": "16:30", "salida": "20:26"},
    ]
    assert dia["marcas"][0]["fecha_hora"] == "2026-09-15T05:45:00-06:00"
    assert dia["trabajado"] == {"minutos": 736, "texto": "12:16"}
    assert dia["completo"] is True
    assert dia["observacion"] is None


@pytest.mark.django_db
def test_el_dia_incompleto_trae_la_salida_en_null(api, con_marcas):
    datos = api("asistencia", {**RANGO, "person_id": "16"}).json()
    dia = datos["personas"][0]["dias"][0]
    assert dia["tramos"] == [{"entrada": "05:49", "salida": None}]
    assert dia["completo"] is False
    assert "Falta la salida" in dia["observacion"]


@pytest.mark.django_db
def test_filtrar_por_codigo_de_planilla(api, maria, usuario):
    marcar("1024", "Maria", MARTES, time(8, 0))
    crear_marca_manual(maria, datetime_local(MARTES, time(17, 0)), "olvido", "Lo vio el guarda.", usuario)
    marcar("16", "BRAYAN JORGE SOLANO GUIDO", MARTES, time(5, 49))

    datos = api("asistencia", {**RANGO, "codigo": "E-0042"}).json()
    [persona] = datos["personas"]
    assert persona["codigo_planilla"] == "E-0042"
    assert persona["total_trabajado"]["minutos"] == 540
    assert [m["origen"] for m in persona["dias"][0]["marcas"]] == ["reloj", "manual"]


@pytest.mark.django_db
def test_los_numeros_coinciden_con_el_reporte(api, con_marcas, client, usuario):
    """La API y el Excel usan el mismo armado: no pueden dar horas distintas."""
    client.force_login(usuario)
    reporte = client.get("/reportes/", RANGO).context["personas"]
    api_datos = api("resumen", RANGO).json()["personas"]
    assert {p.person_id: p.minutos for p in reporte} == {
        p["person_id"]: p["total_trabajado"]["minutos"] for p in api_datos
    }


@pytest.mark.django_db
def test_marcas_crudas_con_reloj_y_metodo(api, con_marcas):
    datos = api("marcas", {**RANGO, "person_id": "16"}).json()
    [m] = datos["marcas"]
    assert m["hora"] == "05:49:00"
    assert m["fecha"] == "2026-09-15"
    assert m["anulada"] is False
    assert "reloj" in m and "metodo" in m


@pytest.mark.django_db
def test_los_acentos_salen_legibles(api, db):
    marcar("185", "DELGADO MUÑOZ MARBETH SAMANTHA", MARTES, time(6, 0))
    r = api("resumen", RANGO)
    assert "MUÑOZ" in r.content.decode("utf-8")
