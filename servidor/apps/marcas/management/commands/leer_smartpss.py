"""Lee las marcas que SmartPSS dejo en esta misma base.

Es la alternativa al agente, para cuando SmartPSS escribe directamente en la base
del sistema. No hay nada que transportar entre maquinas: se lee la tabla y se
entrega al mismo servicio de ingesta que usa el agente.

    manage.py leer_smartpss --explorar     encuentra la tabla que creo SmartPSS
    manage.py leer_smartpss                una pasada
    manage.py leer_smartpss --continuo     se queda corriendo cada minuto

No hace falta estado en disco: la marca de agua sale de la propia base, de la
marca mas reciente que ya se importo, menos la ventana de relectura.
"""

import time
from datetime import date, datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from apps.core.models import Sucursal
from apps.core.tiempo import CR
from apps.marcas import lector_directo
from apps.marcas.models import MarcaReloj
from apps.marcas.servicio import ingestar

LOTE_MAX = 2000


class Command(BaseCommand):
    help = "Importa las marcas que SmartPSS escribio en esta base."

    def add_arguments(self, parser):
        parser.add_argument(
            "--explorar", action="store_true",
            help="busca la tabla de SmartPSS en esta base y muestra que contiene",
        )
        parser.add_argument("--tabla", help="nombre de la tabla; por defecto SMARTPSS_TABLA")
        parser.add_argument(
            "--sucursal", help="codigo de agente; obligatorio si hay mas de una",
        )
        parser.add_argument(
            "--desde", help="AAAA-MM-DD; ignora la marca de agua y relee desde esa fecha",
        )
        parser.add_argument(
            "--continuo", action="store_true", help="repetir cada INTERVALO segundos",
        )
        parser.add_argument("--intervalo", type=int, default=60)

    def handle(self, *args, **opciones):
        if opciones["explorar"]:
            return self._explorar()

        tabla = opciones["tabla"] or settings.SMARTPSS_TABLA
        try:
            lector_directo.validar_nombre(tabla)
        except lector_directo.TablaInvalida as error:
            raise CommandError(str(error))

        sucursal = self._sucursal(opciones.get("sucursal"))

        if not opciones["continuo"]:
            self._una_pasada(tabla, sucursal, opciones.get("desde"))
            return

        self.stdout.write(
            f"Leyendo '{tabla}' cada {opciones['intervalo']} s. Ctrl+C para detener."
        )
        while True:
            try:
                self._una_pasada(tabla, sucursal, opciones.get("desde"))
            except KeyboardInterrupt:
                self.stdout.write("Detenido.")
                return
            except Exception as error:  # noqa: BLE001 - es un proceso que no debe caerse
                self.stderr.write(self.style.ERROR(f"Error en la pasada: {error}"))
            time.sleep(opciones["intervalo"])

    # ------------------------------------------------------------------ pasada

    def _una_pasada(self, tabla: str, sucursal: Sucursal, desde: str | None) -> None:
        utc_ms = self._marca_de_agua(sucursal, desde)
        marcas = lector_directo.leer_desde(tabla, utc_ms, LOTE_MAX)
        resultado = ingestar(sucursal, marcas)
        momento = datetime.now(tz=CR).strftime("%H:%M:%S")
        mensaje = (
            f"{momento}  leidas {resultado['recibidas']}, "
            f"nuevas {resultado['nuevas']}, "
            f"duplicadas {resultado['duplicadas']}, "
            f"sin empleado {resultado['sin_empleado']}"
        )
        estilo = self.style.SUCCESS if resultado["nuevas"] else self.style.HTTP_INFO
        self.stdout.write(estilo(mensaje))

    def _marca_de_agua(self, sucursal: Sucursal, desde: str | None) -> int:
        """Desde donde leer. Se relee hacia atras porque SmartPSS puede escribir
        marcas con horas pasadas cuando vuelve de estar cerrado. Los duplicados
        los descarta la ingesta, asi que releer nunca hace dano."""
        if desde:
            try:
                dia = date.fromisoformat(desde)
            except ValueError:
                raise CommandError(f"--desde '{desde}' no es AAAA-MM-DD")
            return int(
                datetime(dia.year, dia.month, dia.day, tzinfo=CR).timestamp() * 1000
            )

        ultimo = MarcaReloj.objects.filter(sucursal=sucursal).aggregate(
            tope=Max("utc_ms")
        )["tope"]
        if ultimo is not None:
            return ultimo - settings.SMARTPSS_VENTANA_HORAS * 3600 * 1000

        if settings.SMARTPSS_FECHA_INICIO:
            dia = date.fromisoformat(settings.SMARTPSS_FECHA_INICIO)
            return int(
                datetime(dia.year, dia.month, dia.day, tzinfo=CR).timestamp() * 1000
            )
        return 0

    def _sucursal(self, codigo: str | None) -> Sucursal:
        if codigo:
            try:
                return Sucursal.objects.get(codigo_agente=codigo)
            except Sucursal.DoesNotExist:
                raise CommandError(f"No existe una sucursal con codigo '{codigo}'.")
        sucursales = list(Sucursal.objects.filter(activa=True))
        if not sucursales:
            raise CommandError(
                "No hay ninguna sucursal. Cree una primero:\n"
                '  manage.py crear_sucursal --nombre "Oficina Central" '
                "--codigo-agente oficina-central"
            )
        if len(sucursales) > 1:
            raise CommandError(
                "Hay mas de una sucursal. Indique cual con --sucursal CODIGO. "
                f"Disponibles: {', '.join(s.codigo_agente for s in sucursales)}"
            )
        return sucursales[0]

    # ---------------------------------------------------------------- explorar

    def _explorar(self) -> None:
        from django.db import connection

        self.stdout.write(
            f"Buscando en la base '{connection.settings_dict.get('NAME')}' "
            f"({connection.vendor}) tablas con la columna AttendanceUtcTime..."
        )
        candidatas = lector_directo.tablas_candidatas()

        if not candidatas:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("No se encontro ninguna."))
            self.stdout.write("")
            self.stdout.write("Eso significa que SmartPSS todavia no ha escrito aqui. Revise:")
            self.stdout.write("  1. Que los cinco campos de SmartPSS apunten a ESTA base.")
            self.stdout.write("  2. Que el interruptor 'Habilitar Base de Datos' este encendido.")
            self.stdout.write("  3. Que alguien haya marcado en el reloj despues de encenderlo:")
            self.stdout.write("     SmartPSS crea la tabla al escribir la primera marca, no al guardar.")
            return

        self.stdout.write(self.style.SUCCESS(f"  {len(candidatas)} tabla(s) encontrada(s)."))
        for tabla in candidatas:
            self.stdout.write("")
            self.stdout.write("=" * 68)
            self._mostrar(lector_directo.resumen_de(tabla))

    def _mostrar(self, resumen: dict) -> None:
        self.stdout.write(f"Tabla: {resumen['tabla']}")
        self.stdout.write(f"Filas: {resumen['total']}")

        menor, mayor = resumen["rango"]
        if mayor:
            fmt = "%Y-%m-%d %H:%M"
            desde = datetime.fromtimestamp(
                lector_directo.a_segundos(menor), tz=timezone.utc
            ).astimezone(CR)
            hasta = datetime.fromtimestamp(
                lector_directo.a_segundos(mayor), tz=timezone.utc
            ).astimezone(CR)
            self.stdout.write(f"Marcas del {desde:{fmt}} al {hasta:{fmt}} (hora de Costa Rica)")

        if resumen["muestra"]:
            self.stdout.write("")
            self.stdout.write("Ultimas marcas:")
            for fila in resumen["muestra"]:
                momento = datetime.fromtimestamp(
                    lector_directo.a_segundos(fila["AttendanceUtcTime"]), tz=timezone.utc
                ).astimezone(CR)
                self.stdout.write(
                    f"  PersonID={str(fila.get('PersonID')):<8} "
                    f"{str(fila.get('PersonName') or '(sin nombre)'):<24} "
                    f"{momento:%Y-%m-%d %H:%M:%S}  "
                    f"dispositivo={fila.get('DeviceName') or '-'}"
                )

            primera = resumen["muestra"][0]
            utc = primera.get("AttendanceUtcTime")
            local = primera.get("AttendanceDateTime")
            self.stdout.write("")
            self.stdout.write("Comprobacion de zona horaria:")
            self.stdout.write(f"  AttendanceUtcTime  = {utc} ({lector_directo.unidad(utc)})")
            self.stdout.write(f"  AttendanceDateTime = {local} ({lector_directo.unidad(local)})")
            if local:
                diferencia = lector_directo.a_segundos(utc) - lector_directo.a_segundos(local)
                horas = diferencia / 3600
                if diferencia == 21600:
                    self.stdout.write(self.style.SUCCESS(
                        f"  Diferencia {horas:g} h: correcto, el reloj esta en UTC-6"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  Diferencia {horas:g} h: se esperaban 6. "
                        "Revise la zona horaria del reloj antes de seguir"
                    ))

        self.stdout.write("")
        self.stdout.write("Para servidor/.env:")
        self.stdout.write(f"  SMARTPSS_TABLA={resumen['tabla']}")
