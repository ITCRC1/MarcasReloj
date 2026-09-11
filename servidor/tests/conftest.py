"""Piezas compartidas por las pruebas que tocan la base de datos."""

from datetime import date, time

import pytest
from django.contrib.auth.models import Group, User

from apps.api.models import ClienteAPI
from apps.core.models import Departamento, Empleado, Sucursal
from apps.core.permisos import ADMINISTRADOR, CONSULTA, RRHH, SUPERVISOR
from apps.horarios.models import AsignacionHorario, BloqueHorario, Horario

CLAVE = "clave-de-prueba-2026"


@pytest.fixture
def sucursal(db):
    s = Sucursal.objects.create(nombre="Oficina Central", codigo_agente="oficina-central")
    s.clave_en_claro = s.rotar_api_key()
    return s


@pytest.fixture
def cliente_api(db):
    c = ClienteAPI.objects.create(nombre="Planillas")
    c.clave_en_claro = c.rotar_api_key()
    return c


@pytest.fixture
def departamentos(sucursal):
    return {
        "admin": Departamento.objects.create(nombre="Administracion", sucursal=sucursal),
        "ops": Departamento.objects.create(nombre="Operaciones", sucursal=sucursal),
    }


@pytest.fixture
def horario_partido(db):
    """L-V 08:00-12:00 y 13:00-17:00, sabado 08:00-12:00, domingo libre."""
    h = Horario.objects.create(
        nombre="Administrativo partido",
        tolerancia_entrada_min=5,
        minimo_extra_min=15,
        ventana_duplicado_min=5,
    )
    for dia in range(5):
        BloqueHorario.objects.create(
            horario=h, dia_semana=dia, orden=1,
            hora_entrada=time(8, 0), hora_salida=time(12, 0))
        BloqueHorario.objects.create(
            horario=h, dia_semana=dia, orden=2,
            hora_entrada=time(13, 0), hora_salida=time(17, 0))
    BloqueHorario.objects.create(
        horario=h, dia_semana=5, orden=1,
        hora_entrada=time(8, 0), hora_salida=time(12, 0))
    return h


@pytest.fixture
def maria(departamentos, horario_partido):
    e = Empleado.objects.create(
        codigo_planilla="E-0042", nombre="Maria Rodriguez",
        person_id_smartpss="1024", departamento=departamentos["admin"],
        fecha_ingreso=date(2024, 1, 15),
    )
    AsignacionHorario.objects.create(
        empleado=e, horario=horario_partido, vigente_desde=date(2024, 1, 15)
    )
    return e


@pytest.fixture
def carlos(departamentos, horario_partido):
    """De otro departamento, para probar el alcance del supervisor."""
    e = Empleado.objects.create(
        codigo_planilla="E-0051", nombre="Carlos Mora",
        person_id_smartpss="1031", departamento=departamentos["ops"],
        fecha_ingreso=date(2024, 1, 15),
    )
    AsignacionHorario.objects.create(
        empleado=e, horario=horario_partido, vigente_desde=date(2024, 1, 15)
    )
    return e


@pytest.fixture
def usuarios(db, departamentos):
    for nombre in (ADMINISTRADOR, RRHH, SUPERVISOR, CONSULTA):
        Group.objects.get_or_create(name=nombre)

    def crear(username, grupo, superusuario=False):
        u = User.objects.create_user(
            username=username, password=CLAVE,
            is_staff=superusuario, is_superuser=superusuario,
        )
        u.groups.add(Group.objects.get(name=grupo))
        return u

    creados = {
        "admin": crear("admin", ADMINISTRADOR, superusuario=True),
        "rrhh": crear("rrhh", RRHH),
        "supervisor": crear("supervisor", SUPERVISOR),
        "consulta": crear("consulta", CONSULTA),
    }
    # El supervisor solo ve Administracion.
    departamentos["admin"].supervisores.add(creados["supervisor"])
    return creados


def marca_json(person_id: str, utc_ms: int, **extra) -> dict:
    base = {
        "person_id": person_id,
        "person_name": "Maria Rodriguez",
        "card_no": "",
        "utc_ms": utc_ms,
        "state": 0,
        "method": 1,
        "device_ip": "192.168.1.201",
        "device_name": "Reloj Entrada",
        "snapshot_path": "",
        "handler": "",
        "remarks": "",
    }
    base.update(extra)
    return base


def utc_ms_de(fecha: date, hora: time) -> int:
    """Milisegundos UTC de una hora local de Costa Rica, como los manda SmartPSS."""
    from apps.core.tiempo import datetime_local

    return int(datetime_local(fecha, hora).timestamp() * 1000)
