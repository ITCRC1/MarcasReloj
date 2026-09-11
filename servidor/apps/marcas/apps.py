import os
import sys

from django.apps import AppConfig


def esta_sirviendo() -> bool:
    """Si este proceso es el que atiende el sitio.

    Solo ahi tiene sentido leer marcas en segundo plano. Un `migrate`, un
    `collectstatic` o una corrida de pruebas terminan enseguida, y levantarles
    un hilo que consulta la base seria ruido en el mejor caso.
    """
    if "pytest" in sys.modules:
        return False

    argv = sys.argv
    if not argv:
        return False

    ejecutable = os.path.basename(argv[0])
    if ejecutable in ("manage.py", "django-admin", "django-admin.py"):
        if "runserver" not in argv:
            return False
        # Con recarga automatica, runserver arranca dos procesos: el que vigila
        # los archivos y el que sirve. Solo el segundo tiene RUN_MAIN.
        return os.environ.get("RUN_MAIN") == "true"

    # gunicorn u otro servidor WSGI.
    return True


class MarcasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.marcas"
    label = "marcas"
    verbose_name = "Marcas"

    def ready(self):
        if esta_sirviendo():
            from apps.marcas import lector_automatico

            lector_automatico.arrancar()
