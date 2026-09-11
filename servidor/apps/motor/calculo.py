"""Motor de calculo diario de asistencia.

Implementa la seccion 7 de docs/especificacion-sistema-asistencia.md.

Este modulo es puro: no importa Django, no hace I/O y no toca la base de datos.
Recibe dataclasses y devuelve dataclasses, para poder probarlo de forma aislada.

Convenciones:

- Todo el tiempo se maneja en minutos enteros. Nunca horas decimales ni float.
- Todos los datetime son aware. Se convierten a America/Costa_Rica para calcular.
- Los segundos se truncan: toda marca se trabaja a nivel de minuto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

CR = ZoneInfo("America/Costa_Rica")

# Estados posibles de un dia (seccion 7.3).
OK = "OK"
ADVERTENCIA = "ADVERTENCIA"
INCONSISTENTE = "INCONSISTENTE"
AUSENTE = "AUSENTE"
JUSTIFICADO = "JUSTIFICADO"
FERIADO = "FERIADO"
LIBRE = "LIBRE"

# Origenes de una marca.
RELOJ = "reloj"
MANUAL = "manual"

MINUTOS_ALERTA_JORNADA_LARGA = 12 * 60


# --------------------------------------------------------------------------
# Interfaz (seccion 7.1)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Bloque:
    """Un tramo programado del horario. Un dia tiene 0, 1 o 2 bloques."""

    entrada: time
    salida: time


@dataclass(frozen=True)
class Marca:
    """Una marca ya reunida para el dia (reloj no anulada o manual aprobada).

    Los tres primeros campos son los de la especificacion. Los dos ultimos
    tienen valor por defecto y existen para poder generar las alertas de la
    seccion 7.6 sin salir del motor:

    - `handler`: viene de SmartPSS; si trae valor, la marca fue modificada alli.
    - `motivo`: motivo de la marca manual, para nombrarlo en la observacion.
    """

    hora: datetime
    origen: str
    ref_id: int
    handler: str = ""
    motivo: str = ""


@dataclass(frozen=True)
class Parametros:
    tolerancia_entrada_min: int = 5
    minimo_extra_min: int = 15
    ventana_duplicado_min: int = 5
    contar_llegada_temprana: bool = False


@dataclass(frozen=True)
class ContextoDia:
    fecha: date
    bloques: tuple[Bloque, ...]  # vacio = dia libre
    es_feriado: bool
    justificacion: str | None  # tipo de justificacion, si existe


@dataclass
class ResultadoDia:
    estado: str
    marcas_usadas: list[Marca]
    marcas_descartadas: list[Marca]
    minutos_esperados: int = 0
    minutos_trabajados: int = 0
    minutos_ordinarios: int = 0
    minutos_extra: int = 0
    minutos_tardia: int = 0
    minutos_salida_anticipada: int = 0
    minutos_no_laborados: int = 0
    minutos_fuera_horario: int = 0
    minutos_feriado: int = 0
    minutos_descanso_trabajado: int = 0
    observaciones: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Auxiliares internos
# --------------------------------------------------------------------------


@dataclass
class _Intervalo:
    """Par de marcas (entrada, salida) en minutos desde la medianoche local."""

    entrada: int
    salida: int
    entrada_efectiva: int
    bloque: int | None = None  # indice del bloque asociado, si hay


def _minutos_de_time(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutos_de_marca(m: Marca) -> int:
    """Minutos desde la medianoche local. Trunca segundos."""
    if m.hora.tzinfo is None or m.hora.tzinfo.utcoffset(m.hora) is None:
        raise ValueError(f"La marca {m.ref_id} tiene un datetime naive; debe ser aware.")
    local = m.hora.astimezone(CR)
    return local.hour * 60 + local.minute


def _interseccion(a_ini: int, a_fin: int, b_ini: int, b_fin: int) -> int:
    """Minutos comunes entre dos tramos. Nunca negativo."""
    return max(0, min(a_fin, b_fin) - max(a_ini, b_ini))


def _quitar_duplicados(
    marcas: list[Marca], ventana_min: int
) -> tuple[list[Marca], list[Marca]]:
    """Descarta las marcas que caen dentro de la ventana desde la ultima conservada.

    Se conserva siempre la primera. El limite es estricto: una marca a exactamente
    `ventana_min` minutos de la anterior se conserva. Es la lectura conservadora:
    ante la duda es preferible dejar el dia INCONSISTENTE para revision humana que
    descartar en silencio una marca legitima.
    """
    conservadas: list[Marca] = []
    descartadas: list[Marca] = []
    minuto_ultima: int | None = None
    for m in marcas:
        minuto = _minutos_de_marca(m)
        if minuto_ultima is not None and (minuto - minuto_ultima) < ventana_min:
            descartadas.append(m)
            continue
        conservadas.append(m)
        minuto_ultima = minuto
    return conservadas, descartadas


def _formar_intervalos(marcas: list[Marca]) -> list[_Intervalo]:
    """Empareja las marcas por posicion: (1,2) y (3,4)."""
    intervalos = []
    for i in range(0, len(marcas) - 1, 2):
        entrada = _minutos_de_marca(marcas[i])
        salida = _minutos_de_marca(marcas[i + 1])
        intervalos.append(_Intervalo(entrada=entrada, salida=salida, entrada_efectiva=entrada))
    return intervalos


def _asociar_bloques(intervalos: list[_Intervalo], bloques: tuple[Bloque, ...]) -> None:
    """Asocia cada intervalo a un bloque (regla 7.4). Modifica los intervalos.

    Con igual o mas intervalos que bloques, se asocia por posicion y el sobrante
    queda sin bloque. Con menos intervalos que bloques, cada intervalo va al
    bloque cuya hora de entrada esta mas cerca de su entrada real.
    """
    if not bloques:
        return
    if len(intervalos) >= len(bloques):
        for i, intervalo in enumerate(intervalos):
            intervalo.bloque = i if i < len(bloques) else None
        return
    for intervalo in intervalos:
        distancias = [
            (abs(intervalo.entrada - _minutos_de_time(b.entrada)), i)
            for i, b in enumerate(bloques)
        ]
        intervalo.bloque = min(distancias)[1]


def _aplicar_entrada_efectiva(
    intervalos: list[_Intervalo], bloques: tuple[Bloque, ...], p: Parametros
) -> None:
    """Calcula la entrada efectiva de cada intervalo asociado a un bloque (7.5)."""
    for intervalo in intervalos:
        if intervalo.bloque is None:
            continue
        programada = _minutos_de_time(bloques[intervalo.bloque].entrada)
        real = intervalo.entrada
        if real < programada:
            # Llegada temprana: se recorta a la hora programada salvo que cuente.
            intervalo.entrada_efectiva = real if p.contar_llegada_temprana else programada
        elif real <= programada + p.tolerancia_entrada_min:
            # Dentro de la tolerancia: se perdona el atraso.
            intervalo.entrada_efectiva = programada
        else:
            intervalo.entrada_efectiva = real


def _esperados(bloques: tuple[Bloque, ...]) -> int:
    return sum(
        _minutos_de_time(b.salida) - _minutos_de_time(b.entrada) for b in bloques
    )


def _tipo_de_dia(ctx: ContextoDia) -> str:
    """feriado | libre | laboral. El feriado tiene precedencia sobre el dia libre."""
    if ctx.es_feriado:
        return "feriado"
    if not ctx.bloques:
        return "libre"
    return "laboral"


def _estado_con_marcas(n: int, tipo: str, ctx: ContextoDia, r: ResultadoDia) -> str:
    """Estado de un dia con 2 o 4 marcas validas (tabla 7.3)."""
    if tipo == "feriado":
        return OK
    if tipo == "libre":
        r.observaciones.append("Trabajo en dia libre.")
        return ADVERTENCIA

    estado = OK
    if n == 2 and len(ctx.bloques) == 2:
        r.observaciones.append("Solo 2 marcas en horario partido.")
        estado = ADVERTENCIA
    elif n == 4 and len(ctx.bloques) == 1:
        r.observaciones.append("4 marcas en dia de un bloque.")
        estado = ADVERTENCIA
    if ctx.justificacion:
        r.observaciones.append(
            f"Tiene justificacion ({ctx.justificacion}) y marcas; se calcula normal."
        )
        estado = ADVERTENCIA
    return estado


def _alertas(marcas: list[Marca], r: ResultadoDia) -> None:
    """Alertas de la seccion 7.6. No cambian el calculo."""
    if r.minutos_ordinarios + r.minutos_extra > MINUTOS_ALERTA_JORNADA_LARGA:
        r.observaciones.append(
            "Ordinarios mas extra superan 12 horas en el dia."
        )
    for m in marcas:
        hhmm = m.hora.astimezone(CR).strftime("%H:%M")
        if m.origen == RELOJ and m.handler:
            r.observaciones.append(
                f"La marca de las {hhmm} fue modificada en SmartPSS por {m.handler}."
            )
        if m.origen == MANUAL:
            motivo = f" ({m.motivo})" if m.motivo else ""
            r.observaciones.append(f"La marca de las {hhmm} es manual{motivo}.")


# --------------------------------------------------------------------------
# Calculo
# --------------------------------------------------------------------------


def calcular_dia(marcas: list[Marca], ctx: ContextoDia, p: Parametros) -> ResultadoDia:
    """Calcula el resultado de un dia para un empleado.

    Es idempotente y no tiene efectos secundarios: con las mismas entradas
    devuelve siempre el mismo resultado.

    El motor no sabe que dia es hoy. La regla "no se generan resultados AUSENTE
    para el dia actual ni para dias futuros" (7.3) la aplica el servicio de
    recalculo, que si conoce la fecha actual.
    """
    # 1 y 2. Reunir, ordenar y quitar duplicados.
    ordenadas = sorted(marcas, key=lambda m: m.hora)
    usadas, descartadas = _quitar_duplicados(ordenadas, p.ventana_duplicado_min)

    r = ResultadoDia(estado=OK, marcas_usadas=usadas, marcas_descartadas=descartadas)
    if descartadas:
        r.observaciones.append(
            f"{len(descartadas)} marca(s) descartada(s) por duplicado."
        )

    tipo = _tipo_de_dia(ctx)
    esperados = 0 if tipo in ("feriado", "libre") else _esperados(ctx.bloques)
    n = len(usadas)

    # 3. Estado segun cantidad de marcas y tipo de dia.
    if n == 0:
        if tipo == "feriado":
            r.estado = FERIADO
        elif tipo == "libre":
            r.estado = LIBRE
        elif ctx.justificacion:
            r.estado = JUSTIFICADO
            r.minutos_esperados = esperados
            r.minutos_no_laborados = esperados
            r.observaciones.append(f"Dia justificado: {ctx.justificacion}.")
        else:
            r.estado = AUSENTE
            r.minutos_esperados = esperados
            r.minutos_no_laborados = esperados
        return r

    if n not in (2, 4):
        r.estado = INCONSISTENTE
        r.observaciones.append(
            f"{n} marca(s) valida(s); se esperan 2 o 4. No se calcula hasta corregir."
        )
        return r

    r.estado = _estado_con_marcas(n, tipo, ctx, r)

    # 4. Formar intervalos por posicion.
    intervalos = _formar_intervalos(usadas)

    if tipo in ("feriado", "libre"):
        # Todo lo trabajado va completo al concepto del dia, con horas reales
        # y sin tolerancia. Esperados, ordinarios y extra son 0.
        trabajados = sum(max(0, i.salida - i.entrada) for i in intervalos)
        r.minutos_trabajados = trabajados
        if tipo == "feriado":
            r.minutos_feriado = trabajados
        else:
            r.minutos_descanso_trabajado = trabajados
        _alertas(usadas, r)
        return r

    # 5 y 6. Asociar a bloques y aplicar tolerancia y llegada temprana.
    _asociar_bloques(intervalos, ctx.bloques)
    _aplicar_entrada_efectiva(intervalos, ctx.bloques, p)

    for intervalo in intervalos:
        if intervalo.salida < intervalo.entrada_efectiva:
            r.observaciones.append(
                "Un intervalo termina antes de su entrada efectiva; se cuenta como 0."
            )

    # 7. Clasificar los minutos.
    r.minutos_esperados = esperados
    r.minutos_trabajados = sum(
        max(0, i.salida - i.entrada_efectiva) for i in intervalos
    )

    r.minutos_ordinarios = sum(
        _interseccion(
            i.entrada_efectiva,
            i.salida,
            _minutos_de_time(b.entrada),
            _minutos_de_time(b.salida),
        )
        for i in intervalos
        for b in ctx.bloques
    )

    # Extra: despues de la salida del ultimo bloque, mas lo anterior a la
    # entrada del primero si la llegada temprana cuenta.
    fin_ultimo = _minutos_de_time(ctx.bloques[-1].salida)
    inicio_primero = _minutos_de_time(ctx.bloques[0].entrada)
    candidata = sum(
        _interseccion(i.entrada_efectiva, i.salida, fin_ultimo, 24 * 60)
        for i in intervalos
    )
    if p.contar_llegada_temprana:
        candidata += sum(
            _interseccion(i.entrada_efectiva, i.salida, 0, inicio_primero)
            for i in intervalos
        )
    # Por debajo del minimo no hay extra: esos minutos pasan a fuera de horario.
    r.minutos_extra = candidata if candidata >= p.minimo_extra_min else 0

    r.minutos_fuera_horario = (
        r.minutos_trabajados - r.minutos_ordinarios - r.minutos_extra
    )

    for i in intervalos:
        if i.bloque is None:
            continue
        bloque = ctx.bloques[i.bloque]
        programada_entrada = _minutos_de_time(bloque.entrada)
        programada_salida = _minutos_de_time(bloque.salida)
        if i.entrada > programada_entrada + p.tolerancia_entrada_min:
            # Superada la tolerancia se cuentan todos los minutos, no el excedente.
            r.minutos_tardia += i.entrada - programada_entrada
        r.minutos_salida_anticipada += max(0, programada_salida - i.salida)

    r.minutos_no_laborados = max(0, esperados - r.minutos_ordinarios)

    # 8. Alertas.
    _alertas(usadas, r)
    return r
