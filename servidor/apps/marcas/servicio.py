"""Ingesta de marcas y correcciones controladas (secciones 5 y 8)."""

import logging
from datetime import datetime

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.core.models import Empleado, Sucursal
from apps.core.tiempo import fecha_local, utc_ms_a_datetime
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.motor.models import ResultadoDiario
from apps.motor.servicio import esta_cerrado, recalcular, recalcular_dias

log = logging.getLogger(__name__)


class PeriodoCerrado(Exception):
    """Se intento cambiar algo de un dia que ya se pago."""


def _exigir_periodo_abierto(fecha) -> None:
    if esta_cerrado(fecha):
        raise PeriodoCerrado(
            f"El {fecha} pertenece a un periodo cerrado. "
            "Registre un ajuste en el periodo abierto siguiente."
        )


# --------------------------------------------------------------------------
# Ingesta
# --------------------------------------------------------------------------


@transaction.atomic
def ingestar(sucursal: Sucursal, marcas: list[dict]) -> dict:
    """Guarda un lote del agente. Reenviar el mismo lote no duplica nada.

    Un lote vacio es un latido: no trae marcas pero confirma que el agente vive.
    """
    contador = {"recibidas": len(marcas), "nuevas": 0, "duplicadas": 0, "sin_empleado": 0}
    afectados = set()

    # El PersonID es unico dentro de cada instalacion de SmartPSS, no entre
    # sucursales. Ver docs/decisiones-abiertas.md, punto 5.
    empleados = {
        e.person_id_smartpss: e
        for e in Empleado.objects.filter(
            person_id_smartpss__isnull=False, departamento__sucursal=sucursal
        )
    }

    for cruda in marcas:
        utc_ms = int(cruda["utc_ms"])
        fecha_hora = utc_ms_a_datetime(utc_ms)
        person_id = str(cruda.get("person_id") or "")
        empleado = empleados.get(person_id)
        if empleado is None:
            contador["sin_empleado"] += 1

        _, creada = MarcaReloj.objects.get_or_create(
            sucursal=sucursal,
            person_id=person_id,
            utc_ms=utc_ms,
            device_ip=cruda.get("device_ip") or "",
            defaults={
                "empleado": empleado,
                "person_name": cruda.get("person_name") or "",
                "card_no": cruda.get("card_no") or "",
                "fecha_hora": fecha_hora,
                "fecha_local": fecha_local(fecha_hora),
                "state": int(cruda.get("state") or 0),
                "method": int(cruda.get("method") or 0),
                "device_name": cruda.get("device_name") or "",
                "snapshot_path": cruda.get("snapshot_path") or "",
                "handler": cruda.get("handler") or "",
                "remarks": cruda.get("remarks") or "",
            },
        )
        if creada:
            contador["nuevas"] += 1
            if empleado is not None:
                afectados.add((empleado, fecha_local(fecha_hora)))
        else:
            contador["duplicadas"] += 1

    sucursal.ultima_sincronizacion = timezone.now()
    sucursal.save(update_fields=["ultima_sincronizacion"])

    # El recalculo es sincrono, como dice la seccion 7.8: los volumenes son
    # pequenos y asi el agente recibe la confirmacion cuando el dia ya esta al dia.
    if afectados:
        recalcular_dias(afectados)
    return contador


@transaction.atomic
def mapear_person_id(empleado: Empleado, person_id: str) -> int:
    """Asigna un PersonID a un empleado y adopta todas sus marcas sin asignar."""
    empleado.person_id_smartpss = person_id
    empleado.save(update_fields=["person_id_smartpss"])

    huerfanas = MarcaReloj.objects.filter(
        person_id=person_id, empleado__isnull=True, sucursal=empleado.sucursal
    )
    fechas = set(huerfanas.values_list("fecha_local", flat=True))
    actualizadas = huerfanas.update(empleado=empleado)
    recalcular_dias((empleado, f) for f in fechas)
    return actualizadas


def sugerencias_de_mapeo(empleado: Empleado, limite: int = 5):
    """PersonID sin asignar cuyo nombre en el reloj se parece al del empleado."""
    from django.db.models import Count, Max

    partes = [p for p in empleado.nombre.lower().split() if len(p) > 2]
    qs = MarcaReloj.objects.filter(empleado__isnull=True, sucursal=empleado.sucursal)
    candidatos = (
        qs.values("person_id", "person_name")
        .annotate(marcas=Count("pk"), ultima=Max("fecha_local"))
        .order_by("-marcas")
    )
    con_puntaje = []
    for c in candidatos:
        nombre = (c["person_name"] or "").lower()
        c["coincidencias"] = sum(1 for p in partes if p in nombre)
        con_puntaje.append(c)
    con_puntaje.sort(key=lambda c: (-c["coincidencias"], -c["marcas"]))
    return con_puntaje[:limite]


# --------------------------------------------------------------------------
# Correcciones
# --------------------------------------------------------------------------


@transaction.atomic
def anular_marca(marca: MarcaReloj, usuario, motivo: str) -> None:
    """Las marcas del reloj no se editan ni se borran. Se anulan, con motivo."""
    if not motivo.strip():
        raise ValueError("El motivo de anulacion es obligatorio.")
    _exigir_periodo_abierto(marca.fecha_local)
    marca.anulada = True
    marca.anulada_por = usuario
    marca.anulada_en = timezone.now()
    marca.motivo_anulacion = motivo
    marca._history_user = usuario
    marca.save()
    if marca.empleado_id:
        recalcular(marca.empleado, marca.fecha_local)


@transaction.atomic
def restaurar_marca(marca: MarcaReloj, usuario, motivo: str) -> None:
    if not motivo.strip():
        raise ValueError("El motivo de restauracion es obligatorio.")
    _exigir_periodo_abierto(marca.fecha_local)
    marca.anulada = False
    marca.motivo_anulacion = f"{marca.motivo_anulacion}\nRestaurada: {motivo}".strip()
    marca.anulada_por = None
    marca.anulada_en = None
    marca._history_user = usuario
    marca.save()
    if marca.empleado_id:
        recalcular(marca.empleado, marca.fecha_local)


@transaction.atomic
def crear_marca_manual(
    empleado: Empleado, fecha_hora: datetime, motivo: str, detalle: str, usuario,
    aprobada_directamente: bool,
) -> MarcaManual:
    """RRHH la crea aprobada; el supervisor la deja pendiente. Siempre queda el autor."""
    if not detalle.strip():
        raise ValueError("El detalle es obligatorio.")
    fecha = fecha_local(fecha_hora)
    _exigir_periodo_abierto(fecha)

    manual = MarcaManual(
        empleado=empleado,
        fecha_hora=fecha_hora,
        fecha_local=fecha,
        motivo=motivo,
        detalle=detalle,
        estado="aprobada" if aprobada_directamente else "pendiente",
        creada_por=usuario,
    )
    if aprobada_directamente:
        manual.resuelta_por = usuario
        manual.resuelta_en = timezone.now()
    manual._history_user = usuario
    manual.save()
    if manual.estado == "aprobada":
        recalcular(empleado, fecha)
    return manual


@transaction.atomic
def resolver_marca_manual(
    manual: MarcaManual, usuario, nuevo_estado: str, comentario: str = ""
) -> MarcaManual:
    """Aprueba, rechaza o anula una marca manual. Rechazo y anulacion piden comentario."""
    if nuevo_estado not in ("aprobada", "rechazada", "anulada"):
        raise ValueError(f"Estado invalido: {nuevo_estado}")
    if nuevo_estado in ("rechazada", "anulada") and not comentario.strip():
        raise ValueError("Se requiere un comentario para rechazar o anular.")
    _exigir_periodo_abierto(manual.fecha_local)

    manual.estado = nuevo_estado
    manual.resuelta_por = usuario
    manual.resuelta_en = timezone.now()
    manual.comentario_resolucion = comentario
    manual._history_user = usuario
    manual.save()
    recalcular(manual.empleado, manual.fecha_local)
    return manual


@transaction.atomic
def aceptar_advertencia(resultado: ResultadoDiario, usuario, motivo: str) -> ResultadoDiario:
    """Saca el dia de pendientes. No cambia ni un minuto."""
    if not motivo.strip():
        raise ValueError("El motivo de aceptacion es obligatorio.")
    if resultado.estado != "ADVERTENCIA":
        raise ValueError("Solo se aceptan dias en advertencia.")
    _exigir_periodo_abierto(resultado.fecha)
    resultado.aceptado_por = usuario
    resultado.aceptado_en = timezone.now()
    resultado.motivo_aceptacion = motivo
    resultado.save(update_fields=["aceptado_por", "aceptado_en", "motivo_aceptacion"])
    return resultado
