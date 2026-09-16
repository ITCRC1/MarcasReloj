"""Lee las marcas que SmartPSS dejo en esta misma base.

    manage.py leer_smartpss --explorar     encuentra la tabla que creo SmartPSS
    manage.py leer_smartpss                una pasada
    manage.py leer_smartpss --continuo     se queda corriendo cada minuto

No hace falta guardar estado en ningun lado: la marca de agua sale de la propia
base, de la marca mas reciente que ya se importo, menos la ventana de relectura.
"""

import time
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.tiempo import CR
from apps.marcas import importador, lector_directo


class Command(BaseCommand):
    help = "Importa las marcas que SmartPSS escribio en esta base."

    def add_arguments(self, parser):
        parser.add_argument(
            "--explorar", action="store_true",
            help="busca la tabla de SmartPSS en esta base y muestra que contiene",
        )
        parser.add_argument("--tabla", help="nombre de la tabla; por defecto SMARTPSS_TABLA")
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

        if not opciones["continuo"]:
            self._una_pasada(tabla, opciones.get("desde"))
            return

        self.stdout.write(
            f"Leyendo '{tabla}' cada {opciones['intervalo']} s. Ctrl+C para detener."
        )
        while True:
            try:
                self._una_pasada(tabla, opciones.get("desde"))
            except KeyboardInterrupt:
                self.stdout.write("Detenido.")
                return
            except Exception as error:  # noqa: BLE001 - no debe caerse
                self.stderr.write(self.style.ERROR(f"Error en la pasada: {error}"))
            time.sleep(opciones["intervalo"])

    # ------------------------------------------------------------------ pasada

    def _una_pasada(self, tabla: str, desde: str | None) -> None:
        try:
            resultado = importador.una_pasada(tabla, desde)
        except importador.FechaInvalida as error:
            raise CommandError(f"--desde {error}")
        momento = datetime.now(tz=CR).strftime("%H:%M:%S")
        mensaje = (
            f"{momento}  leidas {resultado['recibidas']}, "
            f"nuevas {resultado['nuevas']}, "
            f"duplicadas {resultado['duplicadas']}, "
            f"empleados nuevos {resultado['empleados_creados']}"
        )
        estilo = self.style.SUCCESS if resultado["nuevas"] else self.style.HTTP_INFO
        self.stdout.write(estilo(mensaje))

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
            self.stdout.write("SmartPSS todavia no ha escrito aqui. Revise:")
            self.stdout.write("  1. Que los cinco campos de SmartPSS apunten a ESTA base.")
            self.stdout.write("  2. Que el interruptor 'Habilitar Base de Datos' este encendido.")
            self.stdout.write("  3. Que alguien haya marcado en el reloj despues de encenderlo:")
            self.stdout.write("     SmartPSS crea la tabla al escribir la primera marca.")
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
                    lector_directo.utc_ms_de_la_fila(fila) / 1000, tz=timezone.utc
                ).astimezone(CR)
                self.stdout.write(
                    f"  PersonID={str(fila.get('PersonID')):<8} "
                    f"{str(fila.get('PersonName') or '(sin nombre)'):<24} "
                    f"{momento:%Y-%m-%d %H:%M:%S}  "
                    f"dispositivo={fila.get('DeviceName') or '-'}"
                )

            self.stdout.write("")
            self.stdout.write(
                "Compare estas horas con el informe de registro de SmartPSS: tienen que "
                "coincidir al segundo. Si estan corridas, la hora no se esta leyendo bien."
            )

        self.stdout.write("")
        self.stdout.write("Para las variables del servicio:")
        self.stdout.write(f"  SMARTPSS_TABLA={resumen['tabla']}")
