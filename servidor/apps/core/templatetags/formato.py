from django import template

from apps.core import tiempo

register = template.Library()


@register.filter
def hm(minutos):
    """Minutos enteros como H:MM. Cero se muestra como raya, para que la tabla respire."""
    if minutos in (None, "", 0):
        return "-"
    return tiempo.formato_hm(minutos)


@register.filter
def hm_cero(minutos):
    """Igual que hm, pero muestra 0:00 en lugar de raya. Para los totales."""
    return tiempo.formato_hm(minutos or 0)


@register.filter
def hora(dt):
    return tiempo.a_local(dt).strftime("%H:%M") if dt else "-"


@register.filter
def color_estado(estado):
    return {
        "OK": "success",
        "ADVERTENCIA": "warning",
        "INCONSISTENTE": "danger",
        "AUSENTE": "danger",
        "JUSTIFICADO": "info",
        "FERIADO": "primary",
        "LIBRE": "secondary",
    }.get(estado, "secondary")


@register.filter
def icono_estado(estado):
    return {"ADVERTENCIA": "⚠", "INCONSISTENTE": "✖"}.get(estado, "")
