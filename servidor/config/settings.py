"""Configuracion del servidor de asistencia.

Lo que no se configura por entorno (seccion 14 de la especificacion):
zona horaria, USE_TZ e idioma. Son parte de las reglas del sistema, no del despliegue.
"""

import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-inseguro-cambiar-en-produccion")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# En Railway el dominio lo asigna la plataforma. Lo ideal es leerlo de
# RAILWAY_PUBLIC_DOMAIN, pero esa variable no siempre llega al contenedor; cuando
# no esta, se acepta el espacio de dominios de Railway, que incluye el host que
# usa su healthcheck. Asi el despliegue no se cae por un dominio que cambio.
DOMINIO_RAILWAY = env("RAILWAY_PUBLIC_DOMAIN", default="")
EN_RAILWAY = bool(
    DOMINIO_RAILWAY
    or env("RAILWAY_ENVIRONMENT_NAME", default="")
    or env("RAILWAY_PROJECT_ID", default="")
    or env("RAILWAY_SERVICE_ID", default="")
)
if DOMINIO_RAILWAY:
    ALLOWED_HOSTS.append(DOMINIO_RAILWAY)
elif EN_RAILWAY:
    ALLOWED_HOSTS.append(".railway.app")


def _origen_de(host: str) -> str:
    """Host de ALLOWED_HOSTS a origen para CSRF. '.dominio' es comodin."""
    return f"https://*{host}" if host.startswith(".") else f"https://{host}"


# Sin esto el formulario de acceso falla con 403 detras de HTTPS, porque Django
# compara el origen del POST contra esta lista.
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        _origen_de(h) for h in ALLOWED_HOSTS if h not in ("127.0.0.1", "localhost", "*")
    ]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.horarios",
    "apps.marcas",
    "apps.motor",
    "apps.reportes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.marcas.lector_automatico.ArrancarLectorMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Railway nombra la variable distinto segun como se enlacen los servicios, y
# ademas ofrece las piezas sueltas (host, usuario, clave, base) como variables
# separadas. Se acepta cualquiera de las formas para no depender de cual se haya
# elegido en la interfaz.
URL_DE_LA_BASE = (
    env("DATABASE_URL", default="")
    or env("MYSQL_URL", default="")
    or env("DATABASE_PUBLIC_URL", default="")
    or env("MYSQL_PUBLIC_URL", default="")
)


def _url_desde_las_piezas() -> str:
    """Arma la direccion cuando solo estan las variables sueltas del MySQL.

    Railway las publica con dos nomenclaturas (MYSQLHOST y MYSQL_HOST), asi que
    se prueban las dos. Si falta cualquiera de las cuatro, no se arma nada:
    media conexion es peor que ninguna, porque falla mas tarde y peor.
    """
    def buscar(*nombres, defecto=""):
        for nombre in nombres:
            valor = env(nombre, default="")
            if valor:
                return valor
        return defecto

    host = buscar("MYSQLHOST", "MYSQL_HOST")
    usuario = buscar("MYSQLUSER", "MYSQL_USER")
    clave = buscar("MYSQLPASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD")
    base = buscar("MYSQLDATABASE", "MYSQL_DATABASE")
    puerto = buscar("MYSQLPORT", "MYSQL_PORT", defecto="3306")

    if host and usuario and clave and base:
        return f"mysql://{usuario}:{clave}@{host}:{puerto}/{base}"
    return ""


if not URL_DE_LA_BASE:
    URL_DE_LA_BASE = _url_desde_las_piezas()


def _pista_segun_lo_que_llego(nombres) -> str:
    """Dice que hacer segun las variables que si estan, no solo que falta."""
    urls = {"DATABASE_URL", "MYSQL_URL", "DATABASE_PUBLIC_URL", "MYSQL_PUBLIC_URL"}
    sueltas = {
        "MYSQLHOST", "MYSQL_HOST", "MYSQLUSER", "MYSQL_USER",
        "MYSQLPASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD",
        "MYSQLDATABASE", "MYSQL_DATABASE", "MYSQLPORT", "MYSQL_PORT",
    }
    presentes_url = sorted(urls & set(nombres))
    presentes_sueltas = sorted(sueltas & set(nombres))

    if presentes_url:
        return (
            f"Esta {', '.join(presentes_url)}, pero llego vacia. Es lo que pasa\n"
            "con ${{MySQL.MYSQL_URL}} cuando el servicio no se llama exactamente\n"
            "MySQL: la referencia no resuelve y el valor queda en blanco.\n"
        )
    if presentes_sueltas:
        return (
            f"Llegaron algunas piezas del MySQL ({', '.join(presentes_sueltas)}),\n"
            "pero no alcanzan para armar la conexion: hacen falta host, usuario,\n"
            "clave y base, las cuatro.\n"
            "\n"
            "MYSQL_DATABASE por si sola es solo el NOMBRE de la base, no la\n"
            "direccion para conectarse.\n"
        )
    return (
        "No llego ninguna variable de base de datos. O no se guardo, o falto\n"
        "pulsar 'Apply changes' en Railway despues de agregarla.\n"
    )

# En Railway el disco del contenedor se borra en cada despliegue. Sin una base
# externa, Django caeria al SQLite local y todo *pareceria* funcionar: las
# migraciones corren, el servidor levanta, y los datos se pierden al siguiente
# despliegue. Ese fallo silencioso cuesta horas de diagnostico, asi que se exige
# la variable.
#
# La comprobacion no aplica a los comandos que no tocan la base: collectstatic
# corre durante el build, cuando las variables del servicio pueden no estar, y
# no tiene por que saber nada de la base de datos.
COMANDOS_SIN_BASE = {"collectstatic", "makemigrations", "check", "help", "version"}
_comando = sys.argv[1] if len(sys.argv) > 1 else ""

if EN_RAILWAY and not URL_DE_LA_BASE and _comando not in COMANDOS_SIN_BASE:
    import os

    from django.core.exceptions import ImproperlyConfigured

    # Se listan los NOMBRES de las variables que si llegaron, nunca sus valores.
    # Sin esto, "falta la variable" y "la variable llego vacia" se ven igual, y
    # la unica forma de distinguirlas es desde adentro del contenedor.
    propias = sorted(
        n for n in os.environ
        if not n.startswith(("RAILWAY_", "NIXPACKS_", "MISE_"))
        and n not in {
            "PATH", "HOME", "HOSTNAME", "PWD", "SHLVL", "_", "LANG", "TERM",
            "VIRTUAL_ENV", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
        }
    )

    raise ImproperlyConfigured(
        "\n"
        "=========================================================\n"
        " No llego la direccion de la base de datos\n"
        "=========================================================\n"
        "\n"
        "Esto corre en Railway, donde el disco del contenedor se borra en cada\n"
        "despliegue. Sin una base externa, los usuarios y las marcas\n"
        "desapareceran sin aviso, asi que el arranque se detiene aqui.\n"
        "\n"
        f"Variables que SI recibio este contenedor ({len(propias)}):\n"
        + ("\n".join(f"    {n}" for n in propias) if propias else "    (ninguna)")
        + "\n"
        "\n"
        + _pista_segun_lo_que_llego(propias)
        + "\n"
        "Lo que se necesita es la direccion COMPLETA, en el servicio web y no en\n"
        "el de MySQL:\n"
        "\n"
        "    DATABASE_URL = mysql://usuario:clave@host:puerto/base\n"
        "\n"
        "Sirve igual con el nombre MYSQL_URL o DATABASE_PUBLIC_URL. Si prefiere\n"
        "las piezas sueltas, tienen que estar las cuatro: MYSQLHOST, MYSQLUSER,\n"
        "MYSQLPASSWORD y MYSQLDATABASE.\n"
    )

DATABASES = {
    "default": env.db_url_config(
        URL_DE_LA_BASE or f"sqlite:///{BASE_DIR / 'asistencia.sqlite3'}"
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Fijo, no configurable. Costa Rica es UTC-6 todo el ano, sin horario de verano.
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Costa_Rica"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Sin manifiesto: el manifiesto obliga a correr collectstatic antes de poder
    # renderizar cualquier plantilla, y rompe las pruebas y el arranque en limpio.
    # Whitenoise igual comprime y cachea.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "core:entrar"
LOGIN_REDIRECT_URL = "reportes:marcas"
LOGOUT_REDIRECT_URL = "core:entrar"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Nombre de la tabla que SmartPSS creo en esta misma base. Se averigua con
# `manage.py leer_smartpss --explorar`. Se puede calificar con la base
# ("otra_base.asistencia") si esta en otra del mismo servidor.
# Por defecto es el nombre que SmartPSS Lite usa siempre: depender de que alguien
# configure la variable dejo al sistema sin importar marcas sin que se notara.
SMARTPSS_TABLA = env("SMARTPSS_TABLA", default="AttendanceRecordInfo")

# Cuanto se relee hacia atras en cada pasada. SmartPSS puede escribir marcas con
# horas pasadas cuando vuelve de estar cerrado.
SMARTPSS_VENTANA_HORAS = env.int("SMARTPSS_VENTANA_HORAS", default=48)

# Desde cuando traer marcas la primera vez, si la base esta vacia.
SMARTPSS_FECHA_INICIO = env("SMARTPSS_FECHA_INICIO", default="")

# El servidor web trae las marcas solo, en un hilo aparte. Sin esto habria que
# correr `manage.py leer_smartpss` a mano y en Railway eso no pasa nunca.
# Apagarlo solo si se decide mover la lectura a un servicio o un cron propio.
SMARTPSS_AUTO = env.bool("SMARTPSS_AUTO", default=True)

# Clave con la que el sistema de planillas consulta la API. Vacia, la API
# responde 503: no puede quedar abierta por olvido. Generarla con:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
API_TOKEN = env("API_TOKEN", default="")

# Cada cuanto revisa si SmartPSS escribio algo nuevo.
SMARTPSS_INTERVALO_SEG = env.int("SMARTPSS_INTERVALO_SEG", default=60)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["consola"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"

# En la red local el servidor habla HTTP plano, asi que forzar HTTPS dejaria el
# sistema inaccesible. En Railway, que si termina TLS, se enciende con
# DJANGO_HTTPS=true y `manage.py check --deploy` queda limpio.
if env.bool("DJANGO_HTTPS", default=False):
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # SECURE_HSTS_PRELOAD queda apagado a proposito: inscribe el dominio en una
    # lista que traen los navegadores de fabrica y sacarlo de ahi toma meses.
    # Es un compromiso que este sistema no necesita.
