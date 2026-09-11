"""Consultas de horario que necesita el motor."""

from datetime import date

from django.db.models import Q

from apps.core.models import Empleado
from apps.horarios.models import AsignacionHorario, Feriado, Horario, Justificacion


def horario_vigente(empleado: Empleado, fecha: date) -> Horario | None:
    """Horario que tenia el empleado esa fecha, aunque despues se lo hayan cambiado.

    Es lo que permite recalcular periodos pasados con la realidad de entonces.
    """
    asignacion = (
        AsignacionHorario.objects.select_related("horario")
        .filter(empleado=empleado, vigente_desde__lte=fecha)
        .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha))
        .order_by("-vigente_desde")
        .first()
    )
    return asignacion.horario if asignacion else None


def es_feriado(fecha: date) -> bool:
    return Feriado.objects.filter(fecha=fecha).exists()


def justificacion_de(empleado: Empleado, fecha: date) -> str | None:
    j = Justificacion.objects.filter(
        empleado=empleado, desde__lte=fecha, hasta__gte=fecha
    ).first()
    return j.tipo if j else None
