"""Encuentra la tabla de asistencia dentro de MySQL.

El nombre de la tabla que usa SmartPSS Lite no esta documentado y cambia segun la
version y segun lo que se haya escrito al configurar la base externa. En vez de
adivinarlo, este modulo se conecta a MySQL, recorre las bases y busca tablas que
tengan la columna `AttendanceUtcTime`, que es la firma inconfundible de la tabla
de marcas.

Solo hace SELECT, SHOW y DESCRIBE. No escribe nada.
"""

import socket

import pymysql

# Codigos de error de MySQL que conviene traducir a algo accionable.
ACCESO_DENEGADO = 1045
BASE_DESCONOCIDA = 1049
NO_CONECTA = 2003

# Bases internas de MySQL: no vale la pena mirarlas.
BASES_DEL_SISTEMA = {"information_schema", "mysql", "performance_schema", "sys"}

# La columna que define a la tabla de marcas.
COLUMNA_FIRMA = "attendanceutctime"

# Otras columnas que esperamos encontrar, para calificar el hallazgo.
COLUMNAS_ESPERADAS = [
    "personid", "personname", "personcardno", "attendancedatetime",
    "attendancestate", "attendancemethod", "deviceipaddress", "devicename",
    "snapshotspath", "handler", "attendanceutctime", "remarks",
]


def hay_algo_escuchando(host: str, puerto: int, espera=5.0) -> bool:
    """Si hay un servicio abierto en ese puerto.

    Separa dos problemas que se ven igual desde afuera: que no exista un MySQL
    (no hay nada escuchando) y que exista pero no nos deje entrar (usuario o
    clave equivocados). El consejo que hay que dar es distinto en cada caso.
    """
    try:
        with socket.create_connection((host, int(puerto)), timeout=espera):
            return True
    except OSError:
        return False


def diagnostico_de_conexion(host, puerto, usuario, error: Exception) -> list[str]:
    """Traduce el fallo de conexion a que hacer al respecto."""
    codigo = error.args[0] if error.args else None

    if codigo == ACCESO_DENEGADO:
        return [
            f"MySQL esta corriendo en {host}:{puerto}, pero rechazo al usuario "
            f"'{usuario}'.",
            "",
            "  El servidor existe: el problema es el usuario o la clave.",
            "  Pruebe con el mismo usuario y clave que puso en SmartPSS Lite,",
            "  en Config -> Base de Datos de Asistencia (Externa).",
        ]

    if codigo == BASE_DESCONOCIDA:
        return [
            f"MySQL respondio, pero no existe la base indicada.",
            "",
            "  Deje SMARTPSS_DB_NAME vacio en el .env para que busque en todas",
            "  las bases que el usuario pueda ver.",
        ]

    if not hay_algo_escuchando(host, puerto):
        return [
            f"No hay nada escuchando en {host}:{puerto}.",
            "",
            "  Ahi no hay un servidor MySQL corriendo. Las opciones son:",
            "",
            "  a) Si en la empresa ya hay un MySQL en otra maquina, ponga su IP",
            f"     en SMARTPSS_DB_HOST (ahora dice {host}) y pida al encargado un",
            "     usuario con permiso para crear una base.",
            "",
            "  b) Si no hay ninguno, hay que instalar MySQL Community Server en",
            "     esta PC. Son unos 15 minutos. Los pasos estan en",
            "     docs/conectar-smartpss.md, paso 1.",
            "",
            "  SmartPSS no crea el servidor MySQL: se conecta a uno que ya exista.",
        ]

    return [
        f"Hay un servicio en {host}:{puerto}, pero no responde como MySQL.",
        "",
        f"  Detalle: {error}",
        "  Revise que el puerto sea el correcto (el de MySQL suele ser 3306).",
    ]


def conectar(host, puerto, usuario, clave, base=None):
    parametros = {
        "host": host,
        "port": int(puerto),
        "user": usuario,
        "password": clave,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 30,
    }
    if base:
        parametros["db"] = base
    return pymysql.connect(**parametros)


def bases_visibles(conexion) -> list[str]:
    with conexion.cursor() as cursor:
        cursor.execute("SHOW DATABASES")
        nombres = [list(f.values())[0] for f in cursor.fetchall()]
    return [n for n in nombres if n.lower() not in BASES_DEL_SISTEMA]


def buscar_tablas(conexion, bases: list[str]) -> list[dict]:
    """Tablas que tienen la columna AttendanceUtcTime, en cualquiera de las bases."""
    marcador = ", ".join(["%s"] * len(bases))
    consulta = (
        "SELECT TABLE_SCHEMA AS base, TABLE_NAME AS tabla "
        "FROM information_schema.COLUMNS "
        f"WHERE LOWER(COLUMN_NAME) = %s AND TABLE_SCHEMA IN ({marcador})"
    )
    with conexion.cursor() as cursor:
        cursor.execute(consulta, (COLUMNA_FIRMA, *bases))
        return list(cursor.fetchall())


def describir(conexion, base: str, tabla: str) -> dict:
    """Columnas, cantidad de filas, rango de fechas y unidades de tiempo."""
    with conexion.cursor() as cursor:
        cursor.execute(
            "SELECT COLUMN_NAME AS nombre, DATA_TYPE AS tipo "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (base, tabla),
        )
        columnas = list(cursor.fetchall())
        presentes = {c["nombre"].lower() for c in columnas}

        cursor.execute(f"SELECT COUNT(*) AS n FROM `{base}`.`{tabla}`")
        total = cursor.fetchone()["n"]

        muestra = []
        rango = None
        if total:
            cursor.execute(
                f"SELECT MIN(AttendanceUtcTime) AS menor, MAX(AttendanceUtcTime) AS mayor "
                f"FROM `{base}`.`{tabla}`"
            )
            rango = cursor.fetchone()
            cursor.execute(
                f"SELECT * FROM `{base}`.`{tabla}` ORDER BY AttendanceUtcTime DESC LIMIT 3"
            )
            muestra = list(cursor.fetchall())

    faltantes = [c for c in COLUMNAS_ESPERADAS if c not in presentes]
    return {
        "base": base,
        "tabla": tabla,
        "columnas": columnas,
        "total": total,
        "rango": rango,
        "muestra": muestra,
        "faltantes": faltantes,
        "coincidencia": len(COLUMNAS_ESPERADAS) - len(faltantes),
    }


def unidad(valor: int) -> str:
    """13 digitos son milisegundos, 10 son segundos."""
    if valor is None:
        return "?"
    return "ms" if abs(int(valor)) > 10**12 else "s"


def a_segundos(valor: int) -> int:
    return int(valor) // 1000 if unidad(valor) == "ms" else int(valor)


def informe(hallazgo: dict) -> str:
    """Texto legible de un hallazgo, listo para pegar en el .env."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    CR = ZoneInfo("America/Costa_Rica")
    lineas = []
    lineas.append(f"Base:   {hallazgo['base']}")
    lineas.append(f"Tabla:  {hallazgo['tabla']}")
    lineas.append(f"Filas:  {hallazgo['total']}")
    lineas.append(
        f"Columnas conocidas: {hallazgo['coincidencia']} de {len(COLUMNAS_ESPERADAS)}"
    )
    if hallazgo["faltantes"]:
        lineas.append(f"  Faltan: {', '.join(hallazgo['faltantes'])}")

    if hallazgo["rango"] and hallazgo["rango"]["mayor"]:
        menor = a_segundos(hallazgo["rango"]["menor"])
        mayor = a_segundos(hallazgo["rango"]["mayor"])
        fmt = "%Y-%m-%d %H:%M"
        lineas.append(
            "Marcas desde "
            f"{datetime.fromtimestamp(menor, tz=timezone.utc).astimezone(CR):{fmt}}"
            " hasta "
            f"{datetime.fromtimestamp(mayor, tz=timezone.utc).astimezone(CR):{fmt}}"
            " (hora de Costa Rica)"
        )

    if hallazgo["muestra"]:
        lineas.append("")
        lineas.append("Ultimas 3 marcas:")
        for fila in hallazgo["muestra"]:
            utc = fila.get("AttendanceUtcTime")
            local = fila.get("AttendanceDateTime")
            momento = datetime.fromtimestamp(a_segundos(utc), tz=timezone.utc).astimezone(CR)
            lineas.append(
                f"  PersonID={fila.get('PersonID')!s:<8} "
                f"{fila.get('PersonName') or '(sin nombre)'!s:<22} "
                f"{momento:%Y-%m-%d %H:%M:%S} CR   "
                f"metodo={fila.get('AttendanceMethod')} "
                f"dispositivo={fila.get('DeviceName') or '-'}"
            )

        primera = hallazgo["muestra"][0]
        utc = primera.get("AttendanceUtcTime")
        local = primera.get("AttendanceDateTime")
        lineas.append("")
        lineas.append("Comprobacion de la zona horaria (seccion 21):")
        lineas.append(f"  AttendanceUtcTime  = {utc} ({unidad(utc)})")
        lineas.append(f"  AttendanceDateTime = {local} ({unidad(local)})")
        if local:
            diferencia = a_segundos(utc) - a_segundos(local)
            horas = diferencia / 3600
            if diferencia == 21600:
                veredicto = "correcto: el reloj esta en UTC-6, como Costa Rica"
            else:
                veredicto = (
                    f"INESPERADO: son {horas:g} horas y se esperaban 6. "
                    "Revise la zona horaria del reloj antes de seguir"
                )
            lineas.append(f"  Diferencia: {diferencia} s ({horas:g} h) -> {veredicto}")
        else:
            lineas.append("  AttendanceDateTime viene vacio; no se puede comprobar.")

    lineas.append("")
    lineas.append("Para agente/.env:")
    lineas.append(f"  SMARTPSS_DB_NAME={hallazgo['base']}")
    lineas.append(f"  SMARTPSS_TABLA={hallazgo['tabla']}")
    return "\n".join(lineas)


def explorar(host, puerto, usuario, clave, base=None) -> int:
    """Busca la tabla de marcas y muestra todo lo necesario para configurar el agente."""
    print(f"Conectando a MySQL en {host}:{puerto} como '{usuario}'...")
    try:
        conexion = conectar(host, puerto, usuario, clave)
    except pymysql.MySQLError as error:
        print()
        for linea in diagnostico_de_conexion(host, puerto, usuario, error):
            print(linea)
        return 1

    with conexion:
        bases = [base] if base else bases_visibles(conexion)
        print(f"  OK. Bases visibles: {', '.join(bases) if bases else '(ninguna)'}")
        print()

        if not bases:
            print("El usuario no ve ninguna base. Revise sus permisos.")
            return 1

        print("Buscando tablas con la columna AttendanceUtcTime...")
        try:
            candidatas = buscar_tablas(conexion, bases)
        except pymysql.MySQLError as error:
            print(f"  No se pudo consultar information_schema: {error}")
            return 1

        if not candidatas:
            print("  No se encontro ninguna.")
            print()
            print("  Eso normalmente significa que SmartPSS todavia no ha escrito marcas")
            print("  en MySQL. Revise en SmartPSS Lite que la base externa este")
            print("  configurada y activa, y espere a que alguien marque en el reloj.")
            return 1

        print(f"  {len(candidatas)} tabla(s) encontrada(s).")
        print()

        hallazgos = [describir(conexion, c["base"], c["tabla"]) for c in candidatas]
        # La que mas se parezca a la tabla esperada y mas marcas tenga va primero.
        hallazgos.sort(key=lambda h: (-h["coincidencia"], -h["total"]))

        for i, hallazgo in enumerate(hallazgos, start=1):
            etiqueta = "  <-- esta es" if i == 1 and len(hallazgos) > 1 else ""
            print("=" * 70)
            print(f"Candidata {i} de {len(hallazgos)}{etiqueta}")
            print("=" * 70)
            print(informe(hallazgo))
            print()

    return 0
