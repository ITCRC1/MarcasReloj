"""Puente entre la base de datos y el motor puro.

Arma el contexto de un dia, llama a `calculo.calcular_dia` y guarda el resultado.
Toda la logica de calculo vive en calculo.py; aqui solo hay lectura, escritura y
lo que depende del calendario.
"""

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.models import Empleado
from apps.core.tiempo import a_local
from apps.horarios.models import Feriado
from apps.motor import calculo
from apps.motor.models import ResultadoDiario

log = logging.getLogger(__name__)


def marcas_del_dia(empleado: Empleado, fecha: date) -> list[calculo.Marca]:
    """Marcas del reloj no anuladas, mas marcas manuales no anuladas."""
    from apps.marcas.models import MarcaManual, MarcaReloj

    marcas = [
        calculo.Marca(
            hora=m.fecha_hora,
            origen=calculo.RELOJ,
            ref_id=m.pk,
            handler=m.handler or "",
        )
        for m in MarcaReloj.objects.filter(
            empleado=empleado, fecha_local=fecha, anulada=False
        )
    ]
    marcas += [
        calculo.Marca(
            hora=m.fecha_hora,
            origen=calculo.MANUAL,
            ref_id=m.pk,
            motivo=m.get_motivo_display(),
        )
        for m in MarcaManual.objects.filter(
            empleado=empleado, fecha_local=fecha, anulada=False
        )
    ]
    return marcas


def contexto_del_dia(empleado: Empleado, fecha: date):
    """Devuelve (ContextoDia, Parametros, horario) para ese empleado y esa fecha."""
    horario = empleado.horario
    bloques = horario.bloques_de(fecha.weekday()) if horario else ()
    ctx = calculo.ContextoDia(
        fecha=fecha,
        bloques=bloques,
        es_feriado=Feriado.objects.filter(fecha=fecha).exists(),
        justificacion=None,
    )
    parametros = horario.parametros() if horario else calculo.Parametros()
    return ctx, parametros, horario


def _snapshot_horario(ctx: calculo.ContextoDia) -> list[dict]:
    return [
        {
            "orden": i + 1,
            "entrada": b.entrada.strftime("%H:%M"),
            "salida": b.salida.strftime("%H:%M"),
        }
        for i, b in enumerate(ctx.bloques)
    ]


def _snapshot_marcas(resultado: calculo.ResultadoDia) -> list[dict]:
    """Las marcas del dia, cada una con el papel que jugo en el calculo.

    El reloj no dice si una marca es entrada o salida: AttendanceState llega
    siempre en 0. El papel sale de la posicion, que es justo como las empareja
    el motor: la primera es entrada, la segunda salida, y asi. Se guarda aqui
    para que la pantalla muestre lo mismo que se calculo y no su propia cuenta.
    """
    filas = [
        {
            "hora": a_local(m.hora).strftime("%H:%M"),
            "origen": m.origen,
            "id": m.ref_id,
            "descartada_por_duplicado": False,
            "papel": "entrada" if i % 2 == 0 else "salida",
            # Una entrada sin salida es lo que deja el dia inconsistente.
            "sin_pareja": i % 2 == 0 and i == len(resultado.marcas_usadas) - 1,
        }
        for i, m in enumerate(resultado.marcas_usadas)
    ]
    filas += [
        {
            "hora": a_local(m.hora).strftime("%H:%M"),
            "origen": m.origen,
            "id": m.ref_id,
            "descartada_por_duplicado": True,
            "papel": "",
            "sin_pareja": False,
        }
        for m in resultado.marcas_descartadas
    ]
    return sorted(filas, key=lambda f: f["hora"])


@transaction.atomic
def recalcular(empleado: Empleado, fecha: date) -> ResultadoDiario | None:
    """Reconstruye el resultado de un dia desde cero. Es idempotente.

    Devuelve None cuando no corresponde guardar nada: empleado que no estaba
    contratado, o una ausencia de hoy o del futuro.
    """
    if not empleado.trabajaba_en(fecha):
        ResultadoDiario.objects.filter(empleado=empleado, fecha=fecha).delete()
        return None

    ctx, parametros, _ = contexto_del_dia(empleado, fecha)
    resultado = calculo.calcular_dia(marcas_del_dia(empleado, fecha), ctx, parametros)

    # El dia todavia no termina: marcar ausente a alguien que quiza aun va a
    # llegar seria un error que aparece y desaparece solo.
    if resultado.estado == calculo.AUSENTE and fecha >= timezone.localdate():
        ResultadoDiario.objects.filter(empleado=empleado, fecha=fecha).delete()
        return None

    obj, _ = ResultadoDiario.objects.update_or_create(
        empleado=empleado,
        fecha=fecha,
        defaults={
            "estado": resultado.estado,
            "horario_snapshot": _snapshot_horario(ctx),
            "marcas_usadas": _snapshot_marcas(resultado),
            "minutos_esperados": resultado.minutos_esperados,
            "minutos_trabajados": resultado.minutos_trabajados,
            "minutos_ordinarios": resultado.minutos_ordinarios,
            "minutos_extra": resultado.minutos_extra,
            "minutos_tardia": resultado.minutos_tardia,
            "minutos_salida_anticipada": resultado.minutos_salida_anticipada,
            "minutos_no_laborados": resultado.minutos_no_laborados,
            "minutos_fuera_horario": resultado.minutos_fuera_horario,
            "minutos_feriado": resultado.minutos_feriado,
            "minutos_descanso_trabajado": resultado.minutos_descanso_trabajado,
            "observaciones": list(resultado.observaciones),
        },
    )
    return obj


def recalcular_rango(desde: date, hasta: date, empleados=None) -> int:
    """Recalcula un rango de fechas. Devuelve cuantos dias se guardaron."""
    if empleados is None:
        empleados = Empleado.objects.filter(activo=True)
    guardados = 0
    dias = (hasta - desde).days + 1
    for empleado in empleados:
        for i in range(dias):
            if recalcular(empleado, desde + timedelta(days=i)) is not None:
                guardados += 1
    return guardados


def recalcular_dias(pares) -> int:
    """Recalcula una lista de (empleado, fecha). Es lo que usan los eventos."""
    guardados = 0
    for empleado, fecha in set(pares):
        if empleado is None:
            continue
        if recalcular(empleado, fecha) is not None:
            guardados += 1
    return guardados
