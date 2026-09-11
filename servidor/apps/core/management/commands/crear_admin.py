"""Crea el usuario administrador sin consola interactiva.

    manage.py crear_admin --usuario admin --clave "..."

O, sin argumentos, tomandolos del entorno:

    ADMIN_INICIAL_USUARIO, ADMIN_INICIAL_CLAVE, ADMIN_INICIAL_CORREO

Pensado para plataformas como Railway, donde no siempre hay una terminal a mano y
`createsuperuser` se queda esperando respuestas que nadie puede dar.

Es idempotente y nunca falla: si el usuario ya existe no lo toca, y si no hay
datos no hace nada. Eso importa porque corre dentro del comando de arranque, y un
error aqui dejaria el servicio sin levantar.
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand



class Command(BaseCommand):
    help = "Crea el usuario administrador a partir de argumentos o del entorno."

    def add_arguments(self, parser):
        parser.add_argument("--usuario")
        parser.add_argument("--clave")
        parser.add_argument("--correo", default="")
        parser.add_argument(
            "--cambiar-clave", action="store_true",
            help="si el usuario ya existe, ponerle la clave indicada",
        )

    def handle(self, *args, **opciones):
        self._anunciar_la_base()

        usuario = opciones.get("usuario") or os.environ.get("ADMIN_INICIAL_USUARIO", "")
        clave = opciones.get("clave") or os.environ.get("ADMIN_INICIAL_CLAVE", "")
        correo = opciones.get("correo") or os.environ.get("ADMIN_INICIAL_CORREO", "")

        if not usuario or not clave:
            # Silencio a proposito: es el caso normal en cada arranque.
            self.stdout.write("crear_admin: sin datos, no se hace nada.")
            return

        existente = User.objects.filter(username=usuario).first()

        if existente:
            existente.is_staff = True
            existente.is_superuser = True
            if correo:
                existente.email = correo
            if opciones["cambiar_clave"]:
                existente.set_password(clave)
            existente.save()
            accion = "actualizado" if opciones["cambiar_clave"] else "ya existia"
            self.stdout.write(self.style.SUCCESS(f"crear_admin: '{usuario}' {accion}."))
            return

        nuevo = User.objects.create_superuser(
            username=usuario, email=correo or "", password=clave
        )
        self.stdout.write(self.style.SUCCESS(f"crear_admin: '{usuario}' creado."))
        self.stdout.write(
            "Borre ADMIN_INICIAL_CLAVE de las variables cuando confirme que entra."
        )

    def _anunciar_la_base(self):
        """Deja en el log contra que base se esta trabajando.

        Es la pregunta que aparece cada vez que algo no cuadra en el despliegue:
        el servidor levanta bien pero los datos no estan donde se esperaba.
        """
        from django.db import connection

        datos = connection.settings_dict
        motor = datos["ENGINE"].rsplit(".", 1)[-1]
        destino = f"{datos['HOST']}/{datos['NAME']}" if datos.get("HOST") else datos["NAME"]
        self.stdout.write(f"Base de datos: {motor} -> {destino}")

