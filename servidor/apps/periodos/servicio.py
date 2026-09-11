"""Validaciones de cierre y armado del resumen del periodo (secciones 9 y 12.2)."""

from dataclasses import dataclass

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.models import Empleado, Sucursal
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import recalcular_rango
from apps.periodos.models import Periodo


@dataclass
class Validacion:
    nombre: str
    ok: bool
    detalle: str


def validaciones_de_cierre(periodo: Periodo, recalcular_antes: bool = True) -> list[Validacion]:
    """Las cinco validaciones de la seccion 9. Las advertencias no bloquean."""
    resultado = []

    if recalcular_antes:
        guardados = recalcular_rango(periodo.desde, periodo.hasta)
        resultado.append(
            Validacion("Periodo recalculado", True, f"{guardados} dia(s) recalculado(s).")
        )
    else:
        resultado.append(
            Validacion("Periodo recalculado", False, "Todavia no se ha recalculado.")
        )

    inconsistentes = ResultadoDiario.objects.filter(
        fecha__range=(periodo.desde, periodo.hasta), estado="INCONSISTENTE"
    ).count()
    resultado.append(
        Validacion(
            "Sin dias inconsistentes",
            inconsistentes == 0,
            "Ninguno." if inconsistentes == 0 else f"{inconsistentes} dia(s) por corregir.",
        )
    )

    pendientes = MarcaManual.objects.filter(
        fecha_local__range=(periodo.desde, periodo.hasta), estado="pendiente"
    ).count()
    resultado.append(
        Validacion(
            "Sin marcas manuales pendientes",
            pendientes == 0,
            "Ninguna." if pendientes == 0 else f"{pendientes} por aprobar o rechazar.",
        )
    )

    sin_empleado = MarcaReloj.objects.filter(
        fecha_local__range=(periodo.desde, periodo.hasta), empleado__isnull=True
    ).count()
    resultado.append(
        Validacion(
            "Sin marcas sin empleado asignado",
            sin_empleado == 0,
            "Ninguna." if sin_empleado == 0 else f"{sin_empleado} marca(s) sin mapear.",
        )
    )

    faltantes = []
    for sucursal in Sucursal.objects.filter(activa=True):
        ultima = sucursal.ultima_sincronizacion
        if ultima is None or ultima.date() <= periodo.hasta:
            faltantes.append(f"{sucursal.nombre}: sin sincronizar despues del {periodo.hasta}")
            continue
        # Refuerzo sobre la validacion de la especificacion: el latido del agente
        # solo prueba que esta vivo. Ver docs/decisiones-abiertas.md, punto 8.
        ultima_marca = (
            MarcaReloj.objects.filter(sucursal=sucursal)
            .order_by("-fecha_local")
            .values_list("fecha_local", flat=True)
            .first()
        )
        if ultima_marca is None or ultima_marca < periodo.hasta:
            faltantes.append(
                f"{sucursal.nombre}: la ultima marca recibida es del "
                f"{ultima_marca or 'nunca'}, anterior al fin del periodo"
            )
    resultado.append(
        Validacion(
            "Sincronizacion completa de las sucursales",
            not faltantes,
            "Todas al dia." if not faltantes else " | ".join(faltantes),
        )
    )
    return resultado


def puede_cerrarse(periodo: Periodo, validaciones) -> bool:
    return periodo.estado != "cerrado" and all(v.ok for v in validaciones)


def cerrar(periodo: Periodo, usuario) -> None:
    """Congela el periodo. No se reabre: lo posterior se registra como Ajuste."""
    validaciones = validaciones_de_cierre(periodo)
    if not puede_cerrarse(periodo, validaciones):
        fallas = [v.nombre for v in validaciones if not v.ok]
        raise ValueError("No se puede cerrar: " + ", ".join(fallas))
    periodo.estado = "cerrado"
    periodo.cerrado_por = usuario
    periodo.cerrado_en = timezone.now()
    periodo.save()
    ResultadoDiario.objects.filter(
        fecha__range=(periodo.desde, periodo.hasta), periodo__isnull=True
    ).update(periodo=periodo)


def advertencias_sin_aceptar(periodo: Periodo) -> int:
    return ResultadoDiario.objects.filter(
        fecha__range=(periodo.desde, periodo.hasta),
        estado="ADVERTENCIA",
        aceptado_en__isnull=True,
    ).count()


def marcas_despues_del_cierre(periodo: Periodo):
    """Marcas del reloj recibidas despues de que el periodo cerro."""
    if not periodo.cerrado_en:
        return MarcaReloj.objects.none()
    return MarcaReloj.objects.filter(
        fecha_local__range=(periodo.desde, periodo.hasta), recibida_en__gt=periodo.cerrado_en
    ).select_related("empleado")


def resumen_periodo(periodo: Periodo, empleados=None) -> list[dict]:
    """Totales por empleado. Es el contenido del reporte 12.2 y del endpoint de la API."""
    if empleados is None:
        empleados = Empleado.objects.select_related("departamento").all()

    # Las sumas llevan prefijo `tot_` a proposito: una anotacion que se llame igual
    # que un campo lo sombrea dentro de los `filter` de los Count que vienen
    # despues, y la consulta termina pidiendo COUNT(*) FILTER (WHERE SUM(...) > 0),
    # que SQLite rechaza. Los nombres finales se arman abajo, en Python.
    CAMPOS_SUMADOS = [
        "minutos_esperados", "minutos_ordinarios", "minutos_extra", "minutos_tardia",
        "minutos_salida_anticipada", "minutos_no_laborados", "minutos_fuera_horario",
        "minutos_feriado", "minutos_descanso_trabajado",
    ]
    sumas = {f"tot_{campo}": Sum(campo) for campo in CAMPOS_SUMADOS}

    agregados = {
        fila["empleado_id"]: fila
        for fila in ResultadoDiario.objects.filter(
            fecha__range=(periodo.desde, periodo.hasta), empleado__in=empleados
        )
        .values("empleado_id")
        .annotate(
            **sumas,
            # Dia laborado: cualquiera con tiempo efectivamente trabajado.
            dias_laborados=Count("pk", filter=Q(minutos_trabajados__gt=0)),
            dias_ausente=Count("pk", filter=Q(estado="AUSENTE")),
            dias_justificados=Count("pk", filter=Q(estado="JUSTIFICADO")),
            # Feriado sin trabajar (estado FERIADO) o feriado trabajado (minutos > 0).
            dias_feriado=Count(
                "pk", filter=Q(estado="FERIADO") | Q(minutos_feriado__gt=0)
            ),
            dias_pendientes=Count(
                "pk",
                filter=Q(estado="INCONSISTENTE")
                | Q(estado="ADVERTENCIA", aceptado_en__isnull=True),
            ),
        )
    }

    ajustes_por_empleado: dict[int, list] = {}
    for ajuste in periodo.ajustes.select_related("empleado").all():
        ajustes_por_empleado.setdefault(ajuste.empleado_id, []).append(ajuste)

    filas = []
    for empleado in empleados:
        datos = agregados.get(empleado.pk)
        if datos is None and empleado.pk not in ajustes_por_empleado:
            continue
        base = {
            "empleado": empleado,
            "codigo_empleado": empleado.codigo_planilla,
            "nombre": empleado.nombre,
            "departamento": empleado.departamento.nombre,
            "minutos_esperados": 0,
            "minutos_ordinarios": 0,
            "minutos_extra": 0,
            "minutos_tardia": 0,
            "minutos_salida_anticipada": 0,
            "minutos_no_laborados": 0,
            "minutos_fuera_horario": 0,
            "minutos_feriado": 0,
            "minutos_descanso_trabajado": 0,
            "dias_laborados": 0,
            "dias_ausente": 0,
            "dias_justificados": 0,
            "dias_feriado": 0,
            "dias_pendientes": 0,
        }
        if datos:
            for clave, valor in datos.items():
                if clave == "empleado_id":
                    continue
                base[clave.removeprefix("tot_")] = valor or 0
        base["ajustes"] = ajustes_por_empleado.get(empleado.pk, [])
        filas.append(base)
    return filas


def tipo_jornada_de(empleado: Empleado, fecha) -> str:
    from apps.horarios.servicio import horario_vigente

    horario = horario_vigente(empleado, fecha)
    return horario.tipo_jornada if horario else ""
