"""Pruebas del motor de calculo.

Los 18 casos de referencia son los de la seccion 7.7 de la especificacion.
Deben pasar todos antes de construir la interfaz.

Horario de prueba "Administrativo partido":
  lunes a viernes 08:00-12:00 y 13:00-17:00 (480 esperados)
  sabado 08:00-12:00 (240 esperados)
  domingo libre
Tolerancia 5, minimo de extra 15, ventana de duplicados 5, llegada temprana no cuenta.
"""

from __future__ import annotations

import itertools
from datetime import date, datetime, time

import pytest

from apps.motor.calculo import (
    ADVERTENCIA,
    AUSENTE,
    CR,
    FERIADO,
    INCONSISTENTE,
    JUSTIFICADO,
    LIBRE,
    OK,
    RELOJ,
    Bloque,
    ContextoDia,
    Marca,
    Parametros,
    calcular_dia,
)

# --------------------------------------------------------------------------
# Horario y fechas de referencia
# --------------------------------------------------------------------------

BLOQUES_ENTRE_SEMANA = (
    Bloque(entrada=time(8, 0), salida=time(12, 0)),
    Bloque(entrada=time(13, 0), salida=time(17, 0)),
)
BLOQUES_SABADO = (Bloque(entrada=time(8, 0), salida=time(12, 0)),)
BLOQUES_DOMINGO = ()

LUNES = date(2026, 9, 7)
SABADO = date(2026, 9, 12)
DOMINGO = date(2026, 9, 13)
DIA_FERIADO = date(2026, 9, 15)  # martes, dia de la independencia

PARAMETROS = Parametros(
    tolerancia_entrada_min=5,
    minimo_extra_min=15,
    ventana_duplicado_min=5,
    contar_llegada_temprana=False,
)


def marca(fecha: date, hhmm: str, ref_id: int = 0, **kwargs) -> Marca:
    hora, minuto = (int(p) for p in hhmm.split(":"))
    return Marca(
        hora=datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=CR),
        origen=kwargs.pop("origen", RELOJ),
        ref_id=ref_id,
        **kwargs,
    )


def marcas(fecha: date, *horas: str) -> list[Marca]:
    return [marca(fecha, h, ref_id=i + 1) for i, h in enumerate(horas)]


def contexto(fecha: date, bloques, es_feriado=False, justificacion=None) -> ContextoDia:
    return ContextoDia(
        fecha=fecha,
        bloques=bloques,
        es_feriado=es_feriado,
        justificacion=justificacion,
    )


# --------------------------------------------------------------------------
# Casos de referencia (seccion 7.7)
# --------------------------------------------------------------------------

# (numero, fecha, bloques, es_feriado, horas, estado, ord, extra, tardia,
#  salida_anticipada, no_laborados, fuera_horario, feriado, descanso)
CASOS = [
    (1, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("07:55", "12:01", "12:58", "17:03"), OK, 480, 0, 0, 0, 0, 4, 0, 0),
    (2, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:04", "12:00", "13:00", "17:00"), OK, 480, 0, 0, 0, 0, 0, 0, 0),
    (3, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:12", "12:00", "13:00", "17:00"), OK, 468, 0, 12, 0, 12, 0, 0, 0),
    (4, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:00", "13:00", "18:30"), OK, 480, 90, 0, 0, 0, 0, 0, 0),
    (5, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:00", "13:00", "17:10"), OK, 480, 0, 0, 0, 0, 10, 0, 0),
    (6, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:15", "13:00", "17:00"), OK, 480, 0, 0, 0, 0, 15, 0, 0),
    (7, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:00", "13:00", "16:30"), OK, 450, 0, 0, 30, 30, 0, 0, 0),
    (8, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "08:02", "12:00", "13:00", "17:00"), OK, 480, 0, 0, 0, 0, 0, 0, 0),
    (9, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "17:00"), ADVERTENCIA, 480, 0, 0, 0, 0, 60, 0, 0),
    (10, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:00"), ADVERTENCIA, 240, 0, 0, 0, 240, 0, 0, 0),
    (11, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("13:00", "17:00"), ADVERTENCIA, 240, 0, 0, 0, 240, 0, 0, 0),
    (12, LUNES, BLOQUES_ENTRE_SEMANA, False,
     ("08:00", "12:00", "17:00"), INCONSISTENTE, 0, 0, 0, 0, 0, 0, 0, 0),
    (13, LUNES, BLOQUES_ENTRE_SEMANA, False,
     (), AUSENTE, 0, 0, 0, 0, 480, 0, 0, 0),
    (14, SABADO, BLOQUES_SABADO, False,
     ("07:58", "12:05"), OK, 240, 0, 0, 0, 0, 5, 0, 0),
    (15, SABADO, BLOQUES_SABADO, False,
     ("08:00", "12:00", "13:00", "15:00"), ADVERTENCIA, 240, 120, 0, 0, 0, 0, 0, 0),
    (16, DOMINGO, BLOQUES_DOMINGO, False,
     ("08:00", "12:00"), ADVERTENCIA, 0, 0, 0, 0, 0, 0, 0, 240),
    (17, DIA_FERIADO, BLOQUES_ENTRE_SEMANA, True,
     (), FERIADO, 0, 0, 0, 0, 0, 0, 0, 0),
    (18, DIA_FERIADO, BLOQUES_ENTRE_SEMANA, True,
     ("08:00", "12:00", "13:00", "17:00"), OK, 0, 0, 0, 0, 0, 0, 480, 0),
]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: f"caso-{c[0]}")
def test_casos_de_referencia(caso):
    (numero, fecha, bloques, es_feriado, horas, estado, ordinarios, extra, tardia,
     salida_anticipada, no_laborados, fuera_horario, feriado, descanso) = caso

    r = calcular_dia(
        marcas(fecha, *horas),
        contexto(fecha, bloques, es_feriado=es_feriado),
        PARAMETROS,
    )

    assert r.estado == estado, f"caso {numero}: estado"
    assert r.minutos_ordinarios == ordinarios, f"caso {numero}: ordinarios"
    assert r.minutos_extra == extra, f"caso {numero}: extra"
    assert r.minutos_tardia == tardia, f"caso {numero}: tardia"
    assert r.minutos_salida_anticipada == salida_anticipada, f"caso {numero}: salida anticipada"
    assert r.minutos_no_laborados == no_laborados, f"caso {numero}: no laborados"
    assert r.minutos_fuera_horario == fuera_horario, f"caso {numero}: fuera de horario"
    assert r.minutos_feriado == feriado, f"caso {numero}: feriado"
    assert r.minutos_descanso_trabajado == descanso, f"caso {numero}: descanso trabajado"


def test_caso_8_descarta_la_marca_duplicada():
    r = calcular_dia(
        marcas(LUNES, "08:00", "08:02", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert len(r.marcas_usadas) == 4
    assert len(r.marcas_descartadas) == 1
    assert r.marcas_descartadas[0].hora.astimezone(CR).strftime("%H:%M") == "08:02"


# --------------------------------------------------------------------------
# Invariantes (seccion 7.5)
# --------------------------------------------------------------------------

MINUTOS = (
    "minutos_esperados", "minutos_trabajados", "minutos_ordinarios",
    "minutos_extra", "minutos_tardia", "minutos_salida_anticipada",
    "minutos_no_laborados", "minutos_fuera_horario", "minutos_feriado",
    "minutos_descanso_trabajado",
)


def verificar_invariantes(r, es_laboral: bool) -> None:
    for campo in MINUTOS:
        assert getattr(r, campo) >= 0, f"{campo} es negativo"
    if es_laboral and r.estado in (OK, ADVERTENCIA):
        assert r.minutos_trabajados == (
            r.minutos_ordinarios + r.minutos_extra + r.minutos_fuera_horario
        ), "trabajados != ordinarios + extra + fuera de horario"
        assert (
            r.minutos_ordinarios + r.minutos_no_laborados == r.minutos_esperados
        ), "ordinarios + no laborados != esperados"


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: f"caso-{c[0]}")
def test_invariantes_en_los_casos_de_referencia(caso):
    _, fecha, bloques, es_feriado, horas = caso[:5]
    r = calcular_dia(
        marcas(fecha, *horas),
        contexto(fecha, bloques, es_feriado=es_feriado),
        PARAMETROS,
    )
    verificar_invariantes(r, es_laboral=bool(bloques) and not es_feriado)


def rejilla(inicio_min: int, fin_min: int, paso: int) -> list[str]:
    return [
        f"{m // 60:02d}:{m % 60:02d}"
        for m in range(inicio_min, fin_min + 1, paso)
    ]


@pytest.mark.parametrize("cantidad", [2, 4])
@pytest.mark.parametrize("temprana", [False, True])
def test_invariantes_en_combinaciones_generadas(cantidad, temprana):
    """Recorre combinaciones de marcas crecientes y verifica las invariantes."""
    p = Parametros(
        tolerancia_entrada_min=5,
        minimo_extra_min=15,
        ventana_duplicado_min=5,
        contar_llegada_temprana=temprana,
    )
    ctx = contexto(LUNES, BLOQUES_ENTRE_SEMANA)
    horas = rejilla(6 * 60, 20 * 60, 30)
    revisadas = 0
    for combinacion in itertools.combinations(horas, cantidad):
        r = calcular_dia(marcas(LUNES, *combinacion), ctx, p)
        verificar_invariantes(r, es_laboral=True)
        revisadas += 1
    assert revisadas > 100


def test_invariantes_con_marcas_muy_juntas():
    """Rejilla fina, para que el descarte por duplicado entre en juego."""
    ctx = contexto(LUNES, BLOQUES_ENTRE_SEMANA)
    horas = rejilla(7 * 60 + 50, 8 * 60, 2) + rejilla(16 * 60 + 55, 17 * 60 + 5, 2)
    for combinacion in itertools.combinations(horas, 4):
        r = calcular_dia(marcas(LUNES, *combinacion), ctx, p=PARAMETROS)
        verificar_invariantes(r, es_laboral=True)


# --------------------------------------------------------------------------
# Reglas sueltas
# --------------------------------------------------------------------------


def test_dia_laboral_sin_marcas_con_justificacion():
    r = calcular_dia(
        [],
        contexto(LUNES, BLOQUES_ENTRE_SEMANA, justificacion="vacaciones"),
        PARAMETROS,
    )
    assert r.estado == JUSTIFICADO
    # Pendiente de confirmar con RRHH (ver docs/decisiones-abiertas.md, punto 1):
    # hoy los minutos de un dia justificado caen en no laborados.
    assert r.minutos_esperados == 480
    assert r.minutos_no_laborados == 480


def test_dia_libre_sin_marcas():
    r = calcular_dia([], contexto(DOMINGO, BLOQUES_DOMINGO), PARAMETROS)
    assert r.estado == LIBRE
    assert r.minutos_esperados == 0


def test_marcas_con_justificacion_generan_advertencia():
    r = calcular_dia(
        marcas(LUNES, "08:00", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA, justificacion="permiso_con_goce"),
        PARAMETROS,
    )
    assert r.estado == ADVERTENCIA
    assert any("justificacion" in o for o in r.observaciones)
    assert r.minutos_ordinarios == 480


def test_llegada_temprana_cuenta_como_extra_cuando_se_activa():
    p = Parametros(contar_llegada_temprana=True)
    r = calcular_dia(
        marcas(LUNES, "07:30", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        p,
    )
    assert r.minutos_ordinarios == 480
    assert r.minutos_extra == 30
    assert r.minutos_trabajados == 510


def test_llegada_temprana_por_debajo_del_minimo_va_a_fuera_de_horario():
    p = Parametros(contar_llegada_temprana=True)
    r = calcular_dia(
        marcas(LUNES, "07:50", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        p,
    )
    assert r.minutos_extra == 0
    assert r.minutos_fuera_horario == 10


def test_tardia_cuenta_todos_los_minutos_no_solo_el_excedente():
    r = calcular_dia(
        marcas(LUNES, "08:20", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert r.minutos_tardia == 20


def test_tardia_en_el_limite_exacto_de_la_tolerancia_no_cuenta():
    r = calcular_dia(
        marcas(LUNES, "08:05", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert r.minutos_tardia == 0
    assert r.minutos_ordinarios == 480


def test_tardia_en_los_dos_bloques_se_suma():
    r = calcular_dia(
        marcas(LUNES, "08:10", "12:00", "13:20", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert r.minutos_tardia == 30
    assert r.minutos_ordinarios == 450
    assert r.minutos_no_laborados == 30


def test_el_motor_es_idempotente():
    entrada = marcas(LUNES, "08:12", "12:00", "13:00", "17:03")
    ctx = contexto(LUNES, BLOQUES_ENTRE_SEMANA)
    primero = calcular_dia(entrada, ctx, PARAMETROS)
    segundo = calcular_dia(entrada, ctx, PARAMETROS)
    assert primero == segundo


def test_las_marcas_se_ordenan_aunque_lleguen_desordenadas():
    desordenadas = marcas(LUNES, "17:00", "08:00", "13:00", "12:00")
    r = calcular_dia(desordenadas, contexto(LUNES, BLOQUES_ENTRE_SEMANA), PARAMETROS)
    assert r.estado == OK
    assert r.minutos_ordinarios == 480


def test_una_marca_naive_es_un_error():
    naive = Marca(hora=datetime(2026, 9, 7, 8, 0), origen=RELOJ, ref_id=1)
    with pytest.raises(ValueError):
        calcular_dia([naive], contexto(LUNES, BLOQUES_ENTRE_SEMANA), PARAMETROS)


def test_alerta_de_marca_modificada_en_smartpss():
    entrada = marcas(LUNES, "08:00", "12:00", "13:00", "17:00")
    entrada[3] = marca(LUNES, "17:00", ref_id=4, handler="operador1")
    r = calcular_dia(entrada, contexto(LUNES, BLOQUES_ENTRE_SEMANA), PARAMETROS)
    assert any("SmartPSS" in o for o in r.observaciones)


def test_alerta_de_marca_manual():
    entrada = marcas(LUNES, "08:00", "12:00", "13:00")
    entrada.append(marca(LUNES, "17:00", ref_id=4, origen="manual", motivo="olvido"))
    r = calcular_dia(entrada, contexto(LUNES, BLOQUES_ENTRE_SEMANA), PARAMETROS)
    assert any("manual" in o and "olvido" in o for o in r.observaciones)
    assert r.estado == OK


def test_alerta_de_jornada_mayor_a_12_horas():
    r = calcular_dia(
        marcas(LUNES, "08:00", "12:00", "13:00", "21:30"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert any("12 horas" in o for o in r.observaciones)
    assert r.minutos_extra == 270


def test_seis_marcas_son_inconsistentes():
    r = calcular_dia(
        marcas(LUNES, "08:00", "10:00", "10:30", "12:00", "13:00", "17:00"),
        contexto(LUNES, BLOQUES_ENTRE_SEMANA),
        PARAMETROS,
    )
    assert r.estado == INCONSISTENTE
    assert r.minutos_ordinarios == 0


def test_feriado_en_dia_libre_cuenta_como_feriado():
    r = calcular_dia(
        marcas(DOMINGO, "08:00", "12:00"),
        contexto(DOMINGO, BLOQUES_DOMINGO, es_feriado=True),
        PARAMETROS,
    )
    assert r.minutos_feriado == 240
    assert r.minutos_descanso_trabajado == 0


def test_feriado_no_aplica_tolerancia_ni_llegada_temprana():
    r = calcular_dia(
        marcas(DIA_FERIADO, "07:55", "12:00", "13:00", "17:03"),
        contexto(DIA_FERIADO, BLOQUES_ENTRE_SEMANA, es_feriado=True),
        PARAMETROS,
    )
    assert r.minutos_feriado == 488  # horas reales, completas
    assert r.minutos_esperados == 0
