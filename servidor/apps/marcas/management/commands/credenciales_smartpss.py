"""Muestra que escribir en cada campo de la pantalla de SmartPSS.

    manage.py credenciales_smartpss

Toma los datos de DATABASE_URL y los presenta con los nombres exactos que usa
SmartPSS Lite en Config -> Base de Datos de Asistencia (Externa), para no tener
que traducirlos a mano.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Muestra los cinco datos que pide SmartPSS, sacados de DATABASE_URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--con-clave", action="store_true",
            help="mostrar la contrasena en pantalla (por defecto se oculta)",
        )

    def handle(self, *args, **opciones):
        datos = settings.DATABASES["default"]
        motor = datos["ENGINE"].rsplit(".", 1)[-1]

        if motor == "sqlite3":
            self.stdout.write(self.style.ERROR("La base del sistema es SQLite."))
            self.stdout.write("")
            self.stdout.write("SmartPSS no puede escribir en SQLite: solo habla MySQL.")
            self.stdout.write("Para usar la lectura directa, apunte el sistema a su MySQL")
            self.stdout.write("poniendo esto en servidor/.env y corriendo migrate:")
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "  DATABASE_URL=mysql://usuario:clave@servidor:3306/nombre_de_la_base"
            ))
            self.stdout.write("")
            self.stdout.write("Luego vuelva a correr este comando.")
            return

        if motor != "mysql":
            self.stdout.write(self.style.WARNING(
                f"La base del sistema es {motor}, no MySQL. SmartPSS solo habla MySQL, "
                "asi que la lectura directa no aplica: use el agente."
            ))
            return

        host = datos.get("HOST") or "127.0.0.1"
        puerto = datos.get("PORT") or "3306"
        clave = datos.get("PASSWORD") or ""
        mostrada = clave if opciones["con_clave"] else "*" * len(clave) + "   (--con-clave para verla)"

        self.stdout.write("SmartPSS Lite -> Config -> Base de Datos de Asistencia (Externa)")
        self.stdout.write("")
        self.stdout.write(f"  IP Servidor                 {host}")
        self.stdout.write(f"  Puerto servidor             {puerto}")
        self.stdout.write(f"  Nombre de la base de datos  {datos.get('NAME')}")
        self.stdout.write(f"  Nombre Usuario              {datos.get('USER')}")
        self.stdout.write(f"  Contrasena usuario          {mostrada}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "  Y encienda el interruptor 'Habilitar Base de Datos'."
        ))
        self.stdout.write("")

        if host in ("127.0.0.1", "localhost"):
            self.stdout.write(
                "  Aviso: la base dice 127.0.0.1, que para SmartPSS significa 'su propia\n"
                "  maquina'. Si SmartPSS corre en otra PC, ponga ahi la IP de este servidor\n"
                "  y asegurese de que el usuario de MySQL acepte conexiones desde esa IP."
            )
            self.stdout.write("")

        self.stdout.write("Comprobando que el sistema alcance esa base...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                version = cursor.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(f"  OK: MySQL {version} responde."))
            self.stdout.write("")
            self.stdout.write("Siguiente paso, despues de marcar una vez en el reloj:")
            self.stdout.write("  manage.py leer_smartpss --explorar")
        except Exception as error:  # noqa: BLE001 - se reporta tal cual al usuario
            self.stdout.write(self.style.ERROR(f"  FALLO: {error}"))
