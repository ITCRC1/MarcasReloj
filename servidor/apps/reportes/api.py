"""API de solo lectura para el sistema de planillas.

Entrega lo mismo que el reporte, en JSON: usa el mismo armado (dias.py), asi
que la API y el Excel no pueden dar numeros distintos para el mismo rango.

Autenticacion: una sola clave, API_TOKEN, en el encabezado
    Authorization: Bearer <clave>
Sin la variable definida la API responde 503: nunca queda abierta por olvido.

Tiempos: cada cantidad va en minutos enteros (para calcular) y en "H:MM" (para
leer). Las horas de marca van en hora de Costa Rica "HH:MM" y en ISO 8601 con
zona, para que no haya que adivinar la zona horaria del otro lado.
"""

import hmac
from datetime import date
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.http import require_GET

from apps.core.tiempo import a_local, formato_hm
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.reportes import dias as armado

MAX_DIAS = 62


def _error(estado: int, mensaje: str) -> JsonResponse:
    return JsonResponse({"error": mensaje}, status=estado)


def con_clave(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        esperada = settings.API_TOKEN
        if not esperada:
            return _error(503, "La API no esta habilitada: falta definir API_TOKEN en el servidor.")
        recibida = request.headers.get("Authorization", "")
        if not recibida.startswith("Bearer "):
            return _error(401, "Falta el encabezado 'Authorization: Bearer <clave>'.")
        # Comparacion en tiempo constante: no deja adivinar la clave por demoras.
        if not hmac.compare_digest(recibida[len("Bearer "):].strip(), esperada):
            return _error(401, "Clave invalida.")
        return vista(request, *args, **kwargs)

    return envoltura


def _rango(request) -> tuple[date, date] | JsonResponse:
    try:
        desde = date.fromisoformat(request.GET["desde"])
        hasta = date.fromisoformat(request.GET["hasta"])
    except KeyError:
        return _error(400, "Faltan los parametros 'desde' y 'hasta' (AAAA-MM-DD).")
    except ValueError:
        return _error(400, "'desde' y 'hasta' deben tener formato AAAA-MM-DD.")
    if hasta < desde:
        return _error(400, "'hasta' es anterior a 'desde'.")
    if (hasta - desde).days + 1 > MAX_DIAS:
        return _error(400, f"El rango maximo es de {MAX_DIAS} dias; pidalo por partes.")
    return desde, hasta


def _personas(request, desde, hasta) -> list[armado.Persona]:
    reloj = MarcaReloj.objects.filter(
        fecha_local__range=(desde, hasta), anulada=False
    ).select_related("empleado")
    manuales = MarcaManual.objects.filter(
        fecha_local__range=(desde, hasta), anulada=False
    ).select_related("empleado")

    person_id = request.GET.get("person_id", "").strip()
    codigo = request.GET.get("codigo", "").strip()
    if person_id:
        reloj = reloj.filter(person_id=person_id)
        manuales = manuales.filter(empleado__person_id_smartpss=person_id)
    if codigo:
        reloj = reloj.filter(empleado__codigo_planilla=codigo)
        manuales = manuales.filter(empleado__codigo_planilla=codigo)
    return armado.armar_personas(reloj, manuales)


def _tiempo(minutos: int) -> dict:
    return {"minutos": minutos, "texto": formato_hm(minutos)}


def _marca(m, tipo: str) -> dict:
    local = a_local(m.hora)
    return {
        "tipo": tipo,
        "hora": local.strftime("%H:%M"),
        "fecha_hora": local.isoformat(),
        "origen": m.origen,
    }


def _persona_base(p: armado.Persona) -> dict:
    return {"person_id": p.person_id, "codigo_planilla": p.codigo or None, "nombre": p.nombre}


@require_GET
@con_clave
def asistencia(request):
    """Por persona, un registro por dia con sus marcas, horas y observacion."""
    rango = _rango(request)
    if isinstance(rango, JsonResponse):
        return rango
    desde, hasta = rango

    personas = []
    for p in _personas(request, desde, hasta):
        dias_json = []
        for d in p.dias:
            marcas = []
            for entrada, salida in d.pares:
                marcas.append(_marca(entrada, "entrada"))
                if salida is not None:
                    marcas.append(_marca(salida, "salida"))
            dias_json.append({
                "fecha": d.fecha.isoformat(),
                "marcas": marcas,
                "tramos": [
                    {"entrada": a_local(e.hora).strftime("%H:%M"),
                     "salida": a_local(s.hora).strftime("%H:%M") if s else None}
                    for e, s in d.pares
                ],
                "trabajado": _tiempo(d.minutos),
                "completo": d.completo,
                "marcas_repetidas_descartadas": d.repetidas,
                "observacion": d.observacion or None,
            })
        personas.append({
            **_persona_base(p),
            "total_trabajado": _tiempo(p.minutos),
            "dias_con_marcas": len(p.dias),
            "dias_incompletos": p.incompletos,
            "dias": dias_json,
        })

    return JsonResponse({
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "zona_horaria": "America/Costa_Rica",
        "personas": personas,
    }, json_dumps_params={"ensure_ascii": False})


@require_GET
@con_clave
def resumen(request):
    """Una fila por persona con los totales del rango. Lo mas directo para planilla."""
    rango = _rango(request)
    if isinstance(rango, JsonResponse):
        return rango
    desde, hasta = rango

    return JsonResponse({
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "personas": [
            {
                **_persona_base(p),
                "total_trabajado": _tiempo(p.minutos),
                "dias_con_marcas": len(p.dias),
                "dias_incompletos": p.incompletos,
                "fechas_incompletas": [d.fecha.isoformat() for d in p.dias if not d.completo],
            }
            for p in _personas(request, desde, hasta)
        ],
    }, json_dumps_params={"ensure_ascii": False})


@require_GET
@con_clave
def marcas(request):
    """Las marcas del reloj tal como llegaron, para auditar o conciliar."""
    rango = _rango(request)
    if isinstance(rango, JsonResponse):
        return rango
    desde, hasta = rango

    qs = MarcaReloj.objects.filter(fecha_local__range=(desde, hasta)).select_related("empleado")
    if request.GET.get("person_id"):
        qs = qs.filter(person_id=request.GET["person_id"].strip())
    if request.GET.get("codigo"):
        qs = qs.filter(empleado__codigo_planilla=request.GET["codigo"].strip())

    return JsonResponse({
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "marcas": [
            {
                "id": m.pk,
                "person_id": m.person_id,
                "codigo_planilla": m.empleado.codigo_planilla if m.empleado else None,
                "nombre": m.empleado.nombre if m.empleado else m.person_name,
                "fecha": m.fecha_local.isoformat(),
                "hora": m.hora_local.strftime("%H:%M:%S"),
                "fecha_hora": m.hora_local.isoformat(),
                "reloj": m.device_name,
                "metodo": m.metodo_legible,
                "anulada": m.anulada,
            }
            for m in qs.order_by("fecha_hora")
        ],
    }, json_dumps_params={"ensure_ascii": False})


urlpatterns = [
    path("asistencia", asistencia, name="api_asistencia"),
    path("resumen", resumen, name="api_resumen"),
    path("marcas", marcas, name="api_marcas"),
]
