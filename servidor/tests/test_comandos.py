"""Comandos de puesta en marcha."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command


@pytest.mark.django_db
def test_crear_admin_sin_datos_no_hace_nada(monkeypatch):
    """Corre en cada arranque del contenedor: si falla, el servicio no levanta."""
    for variable in ("ADMIN_INICIAL_USUARIO", "ADMIN_INICIAL_CLAVE", "ADMIN_INICIAL_CORREO"):
        monkeypatch.delenv(variable, raising=False)

    call_command("crear_admin")  # no debe lanzar

    assert User.objects.count() == 0


@pytest.mark.django_db
def test_crear_admin_crea_el_superusuario():
    call_command("crear_admin", usuario="jefe", clave="Una-Clave-Larga-2026")

    usuario = User.objects.get(username="jefe")
    assert usuario.is_superuser
    assert usuario.is_staff
    assert usuario.check_password("Una-Clave-Larga-2026")


@pytest.mark.django_db
def test_crear_admin_es_idempotente():
    call_command("crear_admin", usuario="jefe", clave="Una-Clave-Larga-2026")
    call_command("crear_admin", usuario="jefe", clave="Otra-Distinta-2026")

    assert User.objects.filter(username="jefe").count() == 1
    # Sin --cambiar-clave no se toca la clave existente.
    assert User.objects.get(username="jefe").check_password("Una-Clave-Larga-2026")


@pytest.mark.django_db
def test_crear_admin_cambia_la_clave_si_se_pide():
    call_command("crear_admin", usuario="jefe", clave="Una-Clave-Larga-2026")
    call_command("crear_admin", usuario="jefe", clave="Otra-Distinta-2026", cambiar_clave=True)

    assert User.objects.get(username="jefe").check_password("Otra-Distinta-2026")


@pytest.mark.django_db
def test_crear_admin_toma_los_datos_del_entorno(monkeypatch):
    monkeypatch.setenv("ADMIN_INICIAL_USUARIO", "desde_entorno")
    monkeypatch.setenv("ADMIN_INICIAL_CLAVE", "Clave-Del-Entorno-2026")
    monkeypatch.setenv("ADMIN_INICIAL_CORREO", "it@ejemplo.com")

    call_command("crear_admin")

    usuario = User.objects.get(username="desde_entorno")
    assert usuario.email == "it@ejemplo.com"
    assert usuario.is_superuser
