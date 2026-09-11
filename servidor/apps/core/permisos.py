"""Roles y alcance de cada rol (seccion 10 de la especificacion).

Se apoyan en grupos de Django. El alcance del supervisor sale de
`Departamento.supervisores`.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.core.models import Empleado

ADMINISTRADOR = "Administrador"
RRHH = "RRHH"
SUPERVISOR = "Supervisor"
CONSULTA = "Consulta"

GRUPOS = [ADMINISTRADOR, RRHH, SUPERVISOR, CONSULTA]


def grupos(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True))


def rol(user) -> str:
    if not user.is_authenticated:
        return ""
    if user.is_superuser or ADMINISTRADOR in grupos(user):
        return ADMINISTRADOR
    for nombre in (RRHH, SUPERVISOR, CONSULTA):
        if nombre in grupos(user):
            return nombre
    return CONSULTA


def es_admin(user) -> bool:
    return rol(user) == ADMINISTRADOR


def es_rrhh(user) -> bool:
    """Administrador o RRHH. Es quien aprueba, anula, acepta y cierra."""
    return rol(user) in (ADMINISTRADOR, RRHH)


def es_supervisor(user) -> bool:
    return rol(user) == SUPERVISOR


def empleados_visibles(user):
    """Empleados que el usuario puede ver. El supervisor solo ve su equipo."""
    qs = Empleado.objects.select_related("departamento", "departamento__sucursal")
    if es_supervisor(user):
        return qs.filter(departamento__supervisores=user)
    if not user.is_authenticated:
        return qs.none()
    return qs


def puede_ver_empleado(user, empleado: Empleado) -> bool:
    return empleados_visibles(user).filter(pk=empleado.pk).exists()


def exigir_empleado_visible(user, empleado: Empleado) -> None:
    if not puede_ver_empleado(user, empleado):
        raise PermissionDenied("El empleado no pertenece a su alcance.")


def requiere_rrhh(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not es_rrhh(request.user):
            raise PermissionDenied("Se requiere el rol de RRHH.")
        return vista(request, *args, **kwargs)

    return envoltura


def requiere_admin(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not es_admin(request.user):
            raise PermissionDenied("Se requiere el rol de Administrador.")
        return vista(request, *args, **kwargs)

    return envoltura


def puede_crear_marca_manual(user) -> bool:
    return es_rrhh(user) or es_supervisor(user)
