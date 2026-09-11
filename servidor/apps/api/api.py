"""API REST para el sistema de planillas y para los agentes (seccion 13).

Documentacion interactiva en /api/docs.

Reglas para quien consume:
  - Procesar solo periodos con estado "cerrado". Los abiertos todavia cambian.
  - Identificar empleados por codigo_empleado, nunca por nombre.
  - Todos los valores de tiempo son minutos enteros.
"""

import django
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import NinjaAPI, Router

from apps.api.auth import clave_de_agente, clave_de_cliente
from apps.api.schemas import (
    AjusteSalida,
    DetalleSalida,
    DiaSalida,
    EmpleadoSalida,
    Error,
    LoteEntrada,
    LoteRespuesta,
    PeriodoSalida,
    ResumenSalida,
    SaludRespuesta,
)
from apps.core.models import Empleado
from apps.marcas.servicio import ingestar
from apps.motor.models import ResultadoDiario
from apps.periodos.models import Periodo
from apps.periodos.servicio import resumen_periodo, tipo_jornada_de

api = NinjaAPI(
    title="API de Asistencia",
    version="1.0",
    description="Entrega tiempo laborado por empleado y periodo. No calcula dinero.",
    docs_url="/docs",
)

publico = Router(tags=["publico"])
planillas = Router(auth=clave_de_cliente, tags=["planillas"])
agentes = Router(auth=clave_de_agente, tags=["agentes"])


@publico.get("/salud", response=SaludRespuesta, auth=None)
def salud(request):
    """Verificacion de estado. No requiere autenticacion."""
    return {
        "estado": "ok",
        "version": django.get_version(),
        "hora_servidor": timezone.localtime().isoformat(),
    }


@planillas.get("/empleados", response=list[EmpleadoSalida])
def empleados(request, activos: bool = True):
    qs = Empleado.objects.select_related("departamento", "departamento__sucursal")
    if activos:
        qs = qs.filter(activo=True)
    return [
        {
            "codigo_empleado": e.codigo_planilla,
            "nombre": e.nombre,
            "identificacion": e.identificacion,
            "departamento": e.departamento.nombre,
            "sucursal": e.departamento.sucursal.nombre,
            "activo": e.activo,
            "fecha_ingreso": e.fecha_ingreso,
            "fecha_salida": e.fecha_salida,
        }
        for e in qs
    ]


@planillas.get("/periodos", response=list[PeriodoSalida])
def periodos(request, estado: str | None = None):
    qs = Periodo.objects.all()
    if estado:
        qs = qs.filter(estado=estado)
    return list(qs)


@planillas.get("/periodos/{periodo_id}/resumen", response=ResumenSalida)
def resumen(request, periodo_id: int):
    """El endpoint principal: totales por empleado del periodo."""
    periodo = get_object_or_404(Periodo, pk=periodo_id)
    filas = []
    for fila in resumen_periodo(periodo):
        empleado = fila["empleado"]
        filas.append(
            {
                "codigo_empleado": fila["codigo_empleado"],
                "nombre": fila["nombre"],
                "tipo_jornada": tipo_jornada_de(empleado, periodo.hasta),
                "dias_laborados": fila["dias_laborados"],
                "dias_ausente": fila["dias_ausente"],
                "dias_justificados": fila["dias_justificados"],
                "dias_feriado": fila["dias_feriado"],
                "minutos_esperados": fila["minutos_esperados"],
                "minutos_ordinarios": fila["minutos_ordinarios"],
                "minutos_extra": fila["minutos_extra"],
                "minutos_feriado": fila["minutos_feriado"],
                "minutos_descanso_trabajado": fila["minutos_descanso_trabajado"],
                "minutos_tardia": fila["minutos_tardia"],
                "minutos_salida_anticipada": fila["minutos_salida_anticipada"],
                "minutos_no_laborados": fila["minutos_no_laborados"],
                "minutos_fuera_horario": fila["minutos_fuera_horario"],
                "ajustes": [
                    {
                        "concepto": a.concepto,
                        "minutos": a.minutos,
                        "fecha_original": a.fecha_original,
                        "motivo": a.motivo,
                    }
                    for a in fila["ajustes"]
                ],
            }
        )
    return {"periodo": periodo, "empleados": filas}


@planillas.get("/periodos/{periodo_id}/detalle", response={200: DetalleSalida, 404: Error})
def detalle(request, periodo_id: int, empleado: str):
    """Resultado diario de un empleado en el periodo."""
    periodo = get_object_or_404(Periodo, pk=periodo_id)
    try:
        obj = Empleado.objects.get(codigo_planilla=empleado)
    except Empleado.DoesNotExist:
        return 404, {"detalle": f"No existe el empleado {empleado}."}

    dias = []
    resultados = ResultadoDiario.objects.filter(
        empleado=obj, fecha__range=(periodo.desde, periodo.hasta)
    ).order_by("fecha")
    for r in resultados:
        dias.append(
            {
                "fecha": r.fecha,
                "estado": r.estado,
                "marcas": [
                    {"hora": m["hora"], "origen": m["origen"]}
                    for m in r.marcas_usadas
                    if not m.get("descartada_por_duplicado")
                ],
                "minutos_esperados": r.minutos_esperados,
                "minutos_ordinarios": r.minutos_ordinarios,
                "minutos_extra": r.minutos_extra,
                "minutos_tardia": r.minutos_tardia,
                "minutos_salida_anticipada": r.minutos_salida_anticipada,
                "minutos_no_laborados": r.minutos_no_laborados,
                "minutos_fuera_horario": r.minutos_fuera_horario,
                "minutos_feriado": r.minutos_feriado,
                "minutos_descanso_trabajado": r.minutos_descanso_trabajado,
                "observaciones": r.observaciones,
            }
        )
    return 200, {
        "periodo": periodo,
        "codigo_empleado": obj.codigo_planilla,
        "nombre": obj.nombre,
        "dias": dias,
    }


@planillas.get("/periodos/{periodo_id}/ajustes", response=list[AjusteSalida])
def ajustes(request, periodo_id: int):
    periodo = get_object_or_404(Periodo, pk=periodo_id)
    return [
        {
            "concepto": a.concepto,
            "minutos": a.minutos,
            "fecha_original": a.fecha_original,
            "motivo": a.motivo,
            "codigo_empleado": a.empleado.codigo_planilla,
        }
        for a in periodo.ajustes.select_related("empleado")
    ]


@agentes.post("/ingesta/marcas", response={200: LoteRespuesta, 403: Error})
def ingesta_marcas(request, lote: LoteEntrada):
    """Uso exclusivo de los agentes. Reenviar el mismo lote no duplica nada."""
    sucursal = request.sucursal
    if lote.agente != sucursal.codigo_agente:
        return 403, {
            "detalle": (
                f"La clave pertenece a '{sucursal.codigo_agente}' "
                f"y el lote dice ser de '{lote.agente}'."
            )
        }
    return 200, ingestar(sucursal, [m.dict() for m in lote.marcas])


api.add_router("/v1", publico)
api.add_router("/v1", planillas)
api.add_router("/v1", agentes)
