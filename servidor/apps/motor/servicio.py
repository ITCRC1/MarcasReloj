"""Puente entre la base de datos y el motor puro.

Arma el contexto del dia, llama a `calculo.calcular_dia` y guarda el resultado.
Toda la logica de calculo vive en calculo.py; aqui solo hay lectura, escritura y
las reglas que dependen de la base o del calendario.
"""

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.models import Empleado
from apps.core.tiempo import a_local
from apps.horarios import servicio as horarios
from apps.motor import calculo
from apps.motor.models import CAMPOS_DE_MINUTOS, ResultadoDiario

log = logging.getLogger(__name__)


def hoy() -> date:
    return timezone.localdate()


def periodo_de(fecha: date):
    from apps.periodos.models import Periodo

    return Periodo.objects.filter(desde__lte=fecha, hasta__gte=fecha).first()


def esta_cerrado(fecha: date) -> bool:
    periodo = periodo_de(fecha)
    return periodo is not None and periodo.estado == "cerrado"


def marcas_del_dia(empleado: Empleado, fecha: date) -> list[calculo.Marca]:
    """Marcas del reloj no anuladas mas marcas manuales aprobadas (paso 7.2.1)."""
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
            empleado=empleado, fecha_local=fecha, estado="aprobada"
        )
    ]
    return marcas


def contexto_del_dia(empleado: Empleado, fecha: date):
    """Devuelve (ContextoDia, Parametros, horario) para ese empleado y esa fecha."""
    horario = horarios.horario_vigente(empleado, fecha)
    bloques = horario.bloques_de(fecha.weekday()) if horario else ()
    ctx = calculo.ContextoDia(
        fecha=fecha,
        bloques=bloques,
        es_feriado=horarios.es_feriado(fecha),
        justificacion=horarios.justificacion_de(empleado, fecha),
    )
    parametros = horario.parametros() if horario else calculo.Parametros()
    return ctx, parametros, horario


def _snapshot_horario(ctx: calculo.ContextoDia, horario) -> list[dict]:
    return [
        {
            "orden": i + 1,
            "entrada": b.entrada.strftime("%H:%M"),
            "salida": b.salida.strftime("%H:%M"),
        }
        for i, b in enumerate(ctx.bloques)
    ]


def _snapshot_marcas(resultado: calculo.ResultadoDia) -> list[dict]:
    filas = [
        {
            "hora": a_local(m.hora).strftime("%H:%M"),
            "origen": m.origen,
            "id": m.ref_id,
            "descartada_por_duplicado": False,
        }
        for m in resultado.marcas_usadas
    ]
    filas += [
        {
            "hora": a_local(m.hora).strftime("%H:%M"),
            "origen": m.origen,
            "id": m.ref_id,
            "descartada_por_duplicado": True,
        }
        for m in resultado.marcas_descartadas
    ]
    return sorted(filas, key=lambda f: f["hora"])


@transaction.atomic
def recalcular(empleado: Empleado, fecha: date) -> ResultadoDiario | None:
    """Reconstruye el resultado de un dia desde cero. Es idempotente.

    Devuelve None cuando no corresponde guardar nada: periodo cerrado, empleado
    que no estaba contratado o una ausencia de hoy o del futuro.
    """
    if esta_cerrado(fecha):
        log.debug("Periodo cerrado, no se recalcula %s %s", empleado.codigo_planilla, fecha)
        return None

    if not empleado.trabajaba_en(fecha):
        ResultadoDiario.objects.filter(empleado=empleado, fecha=fecha).delete()
        return None

    ctx, parametros, horario = contexto_del_dia(empleado, fecha)
    resultado = calculo.calcular_dia(marcas_del_dia(empleado, fecha), ctx, parametros)

    # Regla 7.3: no se generan ausencias para el dia de hoy ni para dias futuros.
    # El motor no sabe que dia es hoy; la regla se aplica aqui.
    if resultado.estado == calculo.AUSENTE and fecha >= hoy():
        ResultadoDiario.objects.filter(empleado=empleado, fecha=fecha).delete()
        return None

    anterior = ResultadoDiario.objects.filter(empleado=empleado, fecha=fecha).first()
    valores = {
        "periodo": periodo_de(fecha),
        "estado": resultado.estado,
        "horario_snapshot": _snapshot_horario(ctx, horario),
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
    }

    if anterior and _cambio_algo(anterior, valores):
        # Si el dia cambio, la aceptacion previa ya no aplica: vuelve a pendientes.
        valores.update({"aceptado_por": None, "aceptado_en": None, "motivo_aceptacion": ""})

    obj, _ = ResultadoDiario.objects.update_or_create(
        empleado=empleado, fecha=fecha, defaults=valores
    )
    return obj


def _cambio_algo(anterior: ResultadoDiario, valores: dict) -> bool:
    if anterior.estado != valores["estado"]:
        return True
    return any(getattr(anterior, campo) != valores[campo] for campo in CAMPOS_DE_MINUTOS)


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
