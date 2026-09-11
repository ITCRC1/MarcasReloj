"""Crea los cuatro grupos de la seccion 10.

    python manage.py crear_roles

El alcance fino (que ve cada rol, que puede tocar) lo resuelve apps/core/permisos.py.
Los grupos existen para poder asignar usuarios desde el admin de Django.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.permisos import GRUPOS


class Command(BaseCommand):
    help = "Crea los grupos Administrador, RRHH, Supervisor y Consulta."

    def handle(self, *args, **opciones):
        for nombre in GRUPOS:
            grupo, creado = Group.objects.get_or_create(name=nombre)
            estado = "creado" if creado else "ya existia"
            self.stdout.write(f"  {nombre}: {estado}")
        self.stdout.write(self.style.SUCCESS("Roles listos."))
