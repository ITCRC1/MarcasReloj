"""Pruebas de roles y alcance (secciones 10 y 17)."""

from datetime import date, time

import pytest

from apps.core import permisos
from apps.marcas.servicio import crear_marca_manual, ingestar
from tests.conftest import CLAVE, marca_json, utc_ms_de

LUNES = date(2026, 9, 7)


@pytest.mark.django_db
def test_el_supervisor_solo_ve_su_departamento(usuarios, maria, carlos):
    visibles = permisos.empleados_visibles(usuarios["supervisor"])
    assert list(visibles) == [maria]
    assert not permisos.puede_ver_empleado(usuarios["supervisor"], carlos)


@pytest.mark.django_db
def test_rrhh_y_consulta_ven_a_todos(usuarios, maria, carlos):
    for rol in ("admin", "rrhh", "consulta"):
        codigos = set(
            permisos.empleados_visibles(usuarios[rol]).values_list("codigo_planilla", flat=True)
        )
        assert codigos == {"E-0042", "E-0051"}


@pytest.mark.django_db
def test_el_supervisor_no_entra_al_dia_de_otro_departamento(client, usuarios, carlos):
    client.login(username="supervisor", password=CLAVE)
    respuesta = client.get(f"/marcas/dia/{carlos.codigo_planilla}/{LUNES}/")
    assert respuesta.status_code == 403


@pytest.mark.django_db
def test_el_supervisor_si_entra_al_dia_de_su_equipo(client, usuarios, maria):
    client.login(username="supervisor", password=CLAVE)
    respuesta = client.get(f"/marcas/dia/{maria.codigo_planilla}/{LUNES}/")
    assert respuesta.status_code == 200


@pytest.mark.django_db
def test_consulta_no_puede_aprobar_marcas_manuales(client, usuarios, maria):
    from apps.core.tiempo import datetime_local

    manual = crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido", "prueba",
        usuarios["supervisor"], aprobada_directamente=False,
    )
    client.login(username="consulta", password=CLAVE)
    respuesta = client.post(f"/marcas/manual/{manual.pk}/aprobada/")
    assert respuesta.status_code == 403
    manual.refresh_from_db()
    assert manual.estado == "pendiente"


@pytest.mark.django_db
def test_consulta_no_puede_anular_marcas(client, usuarios, maria, sucursal):
    from apps.marcas.models import MarcaReloj

    ingestar(sucursal, [marca_json("1024", utc_ms_de(LUNES, time(8, 0)))])
    marca = MarcaReloj.objects.get()
    client.login(username="consulta", password=CLAVE)
    respuesta = client.post(f"/marcas/marca/{marca.pk}/anular/", {"motivo": "porque si"})
    assert respuesta.status_code == 403
    marca.refresh_from_db()
    assert marca.anulada is False


@pytest.mark.django_db
def test_rrhh_crea_marcas_ya_aprobadas_y_el_supervisor_no(usuarios, maria):
    from apps.core.tiempo import datetime_local

    de_rrhh = crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 0)), "olvido", "detalle",
        usuarios["rrhh"], aprobada_directamente=True,
    )
    de_supervisor = crear_marca_manual(
        maria, datetime_local(LUNES, time(17, 30)), "olvido", "detalle",
        usuarios["supervisor"], aprobada_directamente=False,
    )
    assert de_rrhh.estado == "aprobada"
    assert de_supervisor.estado == "pendiente"


@pytest.mark.django_db
def test_sin_sesion_redirige_a_entrar(client, maria):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert "/entrar/" in respuesta["Location"]
