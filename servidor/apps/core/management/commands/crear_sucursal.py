"""Crea una sucursal y genera su clave de API para el agente.

    python manage.py crear_sucursal --nombre "Oficina Central" --codigo-agente oficina-central

La clave se muestra una sola vez. El sistema guarda solo su hash, asi que si se
pierde hay que generar otra con --rotar.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Sucursal


class Command(BaseCommand):
    help = "Crea una sucursal y muestra su clave de API."

    def add_arguments(self, parser):
        parser.add_argument("--nombre", required=True)
        parser.add_argument(
            "--codigo-agente", required=True, dest="codigo",
            help="Debe coincidir con AGENTE_NOMBRE en el .env del agente.",
        )
        parser.add_argument(
            "--rotar", action="store_true",
            help="Si la sucursal ya existe, generar una clave nueva.",
        )

    def handle(self, *args, **opciones):
        codigo = opciones["codigo"].strip()
        if not codigo:
            raise CommandError("El codigo del agente no puede ir vacio.")

        sucursal, creada = Sucursal.objects.get_or_create(
            codigo_agente=codigo, defaults={"nombre": opciones["nombre"]}
        )
        if not creada and not opciones["rotar"]:
            raise CommandError(
                f"Ya existe la sucursal '{sucursal.nombre}' con ese codigo. "
                "Use --rotar si quiere generar una clave nueva."
            )

        clave = sucursal.rotar_api_key()

        self.stdout.write(self.style.SUCCESS(
            f"Sucursal {'creada' if creada else 'actualizada'}: {sucursal.nombre}"
        ))
        self.stdout.write("")
        self.stdout.write("Ponga esto en agente/.env:")
        self.stdout.write("")
        self.stdout.write(f"  AGENTE_NOMBRE={sucursal.codigo_agente}")
        self.stdout.write(f"  API_KEY={clave}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "Copie la clave ahora. No se vuelve a mostrar: el sistema guarda solo su hash."
        ))
