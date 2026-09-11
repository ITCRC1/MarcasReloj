from apps.core import permisos


def rol_del_usuario(request):
    """Expone el rol y los permisos gruesos a todas las plantillas."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"rol": "", "es_rrhh": False, "es_admin": False, "es_supervisor": False}
    return {
        "rol": permisos.rol(user),
        "es_rrhh": permisos.es_rrhh(user),
        "es_admin": permisos.es_admin(user),
        "es_supervisor": permisos.es_supervisor(user),
    }
