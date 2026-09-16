"""Ingesta de marcas y correcciones."""

import logging
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from apps.core.models import Empleado
from apps.core.tiempo import fecha_local, utc_ms_a_datetime
from apps.marcas.models import MarcaManual, MarcaReloj
from apps.motor.servicio import recalcular, recalcular_dias

log = logging.getLogger(__name__)


def _codigo_libre(person_id: str, ocupados: set[str]) -> str:
    """El codigo de planilla es el PersonID ("Num. empleado" en SmartPSS).

    Si ya lo usa otro empleado creado a mano, se marca de donde viene en vez de
    fallar: la marca no puede quedarse sin dueno por un choque de codigos.
    """
    return person_id if person_id not in ocupados else f"SMARTPSS-{person_id}"


def asegurar_empleados(marcas: list[dict], empleados: dict[str, Empleado]) -> int:
    """Crea el empleado de cada PersonID que el sistema todavia no conoce.

    Los usuarios del reloj son los empleados del sistema: nadie tiene que
    cargarlos dos veces. Se crean con el nombre que trae el reloj y con la
    fecha de su primera marca como ingreso. Horario, departamento y lo demas se
    completan despues en la pantalla del empleado.
    """
    nuevos: dict[str, tuple[str, date]] = {}
    for cruda in marcas:
        person_id = str(cruda.get("person_id") or "")
        if not person_id or person_id in empleados:
            continue
        fecha = fecha_local(utc_ms_a_datetime(int(cruda["utc_ms"])))
        nombre = (cruda.get("person_name") or "").strip() or f"PersonID {person_id}"
        anterior = nuevos.get(person_id)
        if anterior is None or fecha < anterior[1]:
            nuevos[person_id] = (nombre, fecha)

    if not nuevos:
        return 0

    ocupados = set(
        Empleado.objects.filter(codigo_planilla__in=list(nuevos)).values_list(
            "codigo_planilla", flat=True
        )
    )
    for person_id, (nombre, fecha) in nuevos.items():
        empleados[person_id] = Empleado.objects.create(
            codigo_planilla=_codigo_libre(person_id, ocupados),
            nombre=nombre[:120],
            person_id_smartpss=person_id,
            fecha_ingreso=fecha,
        )
    log.info("Se crearon %s empleado(s) nuevos desde el reloj", len(nuevos))
    return len(nuevos)


@transaction.atomic
def adoptar_marcas_sin_empleado() -> int:
    """Da dueno a las marcas que llegaron antes de que existiera su empleado.

    Cubre las marcas importadas cuando el sistema todavia no creaba empleados
    solo. Devuelve cuantos empleados creo. Si no hay huerfanas no hace nada.
    """
    from django.db.models import Max, Min

    huerfanas = (
        MarcaReloj.objects.filter(empleado__isnull=True)
        .exclude(person_id="")
        .values("person_id")
        .annotate(nombre=Max("person_name"), primera=Min("utc_ms"))
    )
    if not huerfanas:
        return 0

    empleados = {
        e.person_id_smartpss: e
        for e in Empleado.objects.filter(person_id_smartpss__isnull=False)
    }
    creados = asegurar_empleados(
        [
            {"person_id": h["person_id"], "person_name": h["nombre"], "utc_ms": h["primera"]}
            for h in huerfanas
        ],
        empleados,
    )
    for h in huerfanas:
        mapear_person_id(empleados[h["person_id"]], h["person_id"])
    return creados


@transaction.atomic
def ingestar(marcas: list[dict]) -> dict:
    """Guarda un lote de marcas de SmartPSS. Reenviarlas no duplica nada."""
    contador = {
        "recibidas": len(marcas), "nuevas": 0, "duplicadas": 0,
        "sin_empleado": 0, "empleados_creados": 0,
    }
    if not marcas:
        return contador

    empleados = {
        e.person_id_smartpss: e
        for e in Empleado.objects.filter(person_id_smartpss__isnull=False)
    }
    contador["empleados_creados"] = asegurar_empleados(marcas, empleados)

    # Se arma todo en memoria y se guarda en bloque. Guardarlas una por una
    # eran varios viajes a la base por marca: con las 3.218 del historial la
    # importacion no terminaba nunca.
    candidatas: dict[tuple, MarcaReloj] = {}
    for cruda in marcas:
        utc_ms = int(cruda["utc_ms"])
        fecha_hora = utc_ms_a_datetime(utc_ms)
        person_id = str(cruda.get("person_id") or "")
        empleado = empleados.get(person_id)
        if empleado is None:
            contador["sin_empleado"] += 1

        llave = (person_id, utc_ms, cruda.get("device_ip") or "")
        candidatas.setdefault(llave, MarcaReloj(
            empleado=empleado,
            person_id=person_id,
            utc_ms=utc_ms,
            device_ip=llave[2],
            person_name=cruda.get("person_name") or "",
            card_no=cruda.get("card_no") or "",
            fecha_hora=fecha_hora,
            fecha_local=fecha_local(fecha_hora),
            method=int(cruda.get("method") or 0),
            device_name=cruda.get("device_name") or "",
            handler=cruda.get("handler") or "",
            remarks=cruda.get("remarks") or "",
        ))

    utcs = [llave[1] for llave in candidatas]
    existentes = set(
        MarcaReloj.objects.filter(utc_ms__gte=min(utcs), utc_ms__lte=max(utcs))
        .values_list("person_id", "utc_ms", "device_ip")
    )
    nuevas = [m for llave, m in candidatas.items() if llave not in existentes]

    # ignore_conflicts por si otro worker guardo la misma marca en este instante.
    MarcaReloj.objects.bulk_create(nuevas, batch_size=500, ignore_conflicts=True)
    contador["nuevas"] = len(nuevas)
    contador["duplicadas"] = len(marcas) - len(nuevas)

    afectados = {(m.empleado, m.fecha_local) for m in nuevas if m.empleado is not None}
    if afectados:
        recalcular_dias(afectados)
    return contador


@transaction.atomic
def mapear_person_id(empleado: Empleado, person_id: str) -> int:
    """Asigna un PersonID a un empleado y adopta todas sus marcas sin asignar."""
    empleado.person_id_smartpss = person_id
    empleado.save(update_fields=["person_id_smartpss"])

    huerfanas = MarcaReloj.objects.filter(person_id=person_id, empleado__isnull=True)
    fechas = set(huerfanas.values_list("fecha_local", flat=True))
    actualizadas = huerfanas.update(empleado=empleado)
    # Sin horario no hay nada que calcular: se calcula al asignarlo.
    if empleado.horario_id:
        recalcular_dias((empleado, f) for f in fechas)
    return actualizadas


def sugerencias_de_mapeo(empleado: Empleado, limite: int = 5):
    """PersonID sin asignar cuyo nombre en el reloj se parece al del empleado."""
    from django.db.models import Count, Max

    partes = [p for p in empleado.nombre.lower().split() if len(p) > 2]
    candidatos = (
        MarcaReloj.objects.filter(empleado__isnull=True)
        .values("person_id", "person_name")
        .annotate(marcas=Count("pk"), ultima=Max("fecha_local"))
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
    marca.anulada = True
    marca.anulada_por = usuario
    marca.anulada_en = timezone.now()
    marca.motivo_anulacion = motivo
    marca.save()
    if marca.empleado_id:
        recalcular(marca.empleado, marca.fecha_local)


@transaction.atomic
def restaurar_marca(marca: MarcaReloj, usuario, motivo: str) -> None:
    if not motivo.strip():
        raise ValueError("El motivo de restauracion es obligatorio.")
    marca.anulada = False
    marca.motivo_anulacion = f"{marca.motivo_anulacion}\nRestaurada: {motivo}".strip()
    marca.anulada_por = usuario
    marca.anulada_en = timezone.now()
    marca.save()
    if marca.empleado_id:
        recalcular(marca.empleado, marca.fecha_local)


@transaction.atomic
def crear_marca_manual(
    empleado: Empleado, fecha_hora: datetime, motivo: str, detalle: str, usuario
) -> MarcaManual:
    """Crea la correccion y recalcula el dia. Queda quien la hizo y por que."""
    if not detalle.strip():
        raise ValueError("El detalle es obligatorio.")
    fecha = fecha_local(fecha_hora)
    manual = MarcaManual.objects.create(
        empleado=empleado,
        fecha_hora=fecha_hora,
        fecha_local=fecha,
        motivo=motivo,
        detalle=detalle,
        creada_por=usuario,
    )
    recalcular(empleado, fecha)
    return manual


@transaction.atomic
def anular_marca_manual(manual: MarcaManual, motivo: str) -> MarcaManual:
    """Una marca manual no se edita: se anula y se crea otra."""
    if not motivo.strip():
        raise ValueError("El motivo de anulacion es obligatorio.")
    manual.anulada = True
    manual.motivo_anulacion = motivo
    manual.save()
    recalcular(manual.empleado, manual.fecha_local)
    return manual
