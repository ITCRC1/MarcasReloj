"""Piezas compartidas por las pruebas que tocan la base de datos."""

from datetime import date, time

import pytest
from django.contrib.auth.models import User

from apps.core.models import Empleado
from apps.horarios.models import BloqueHorario, Horario

CLAVE = "clave-de-prueba-2026"


@pytest.fixture
def usuario(db):
    return User.objects.create_user(username="admin", password=CLAVE, is_superuser=True)


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
def maria(horario_partido):
    return Empleado.objects.create(
        codigo_planilla="E-0042", nombre="Maria Rodriguez",
        person_id_smartpss="1024", departamento="Administracion",
        horario=horario_partido, fecha_ingreso=date(2024, 1, 15),
    )


def marca_json(person_id: str, utc_ms: int, **extra) -> dict:
    base = {
        "person_id": person_id,
        "person_name": "Maria Rodriguez",
        "card_no": "",
        "utc_ms": utc_ms,
        "method": 1,
        "device_ip": "192.168.1.201",
        "device_name": "Reloj Entrada",
        "handler": "",
        "remarks": "",
    }
    base.update(extra)
    return base


def utc_ms_de(fecha: date, hora: time) -> int:
    """Milisegundos UTC de una hora local de Costa Rica, como los manda SmartPSS."""
    from apps.core.tiempo import datetime_local

    return int(datetime_local(fecha, hora).timestamp() * 1000)
