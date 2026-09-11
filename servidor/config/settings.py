"""Configuracion del servidor de asistencia.

Lo que no se configura por entorno (seccion 14 de la especificacion):
zona horaria, USE_TZ e idioma. Son parte de las reglas del sistema, no del despliegue.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-inseguro-cambiar-en-produccion")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Railway asigna el dominio al desplegar y lo publica en esta variable. Se agrega
# solo para no tener que acordarse de copiarlo a mano cada vez que cambia.
DOMINIO_RAILWAY = env("RAILWAY_PUBLIC_DOMAIN", default="")
if DOMINIO_RAILWAY:
    ALLOWED_HOSTS.append(DOMINIO_RAILWAY)
    CSRF_TRUSTED_ORIGINS.append(f"https://{DOMINIO_RAILWAY}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "apps.core",
    "apps.horarios",
    "apps.marcas",
    "apps.motor",
    "apps.periodos",
    "apps.reportes",
    "apps.api",
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
    "simple_history.middleware.HistoryRequestMiddleware",
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
                "apps.core.context.rol_del_usuario",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'asistencia.sqlite3'}"
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
LOGIN_REDIRECT_URL = "core:tablero"
LOGOUT_REDIRECT_URL = "core:entrar"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Minutos sin sincronizar tras los cuales el tablero marca un agente como caido.
ALERTA_AGENTE_MINUTOS = env.int("ALERTA_AGENTE_MINUTOS", default=15)

# Lectura directa: cuando SmartPSS escribe en esta misma base, no hace falta el
# agente. Es el nombre de la tabla que SmartPSS creo aqui. Se puede calificar con
# la base ("otra_base.asistencia") si esta en otra del mismo servidor.
# Vacio = no se usa la lectura directa.
SMARTPSS_TABLA = env("SMARTPSS_TABLA", default="")

# Cuanto se relee hacia atras en cada pasada. SmartPSS puede escribir marcas con
# horas pasadas cuando vuelve de estar cerrado.
SMARTPSS_VENTANA_HORAS = env.int("SMARTPSS_VENTANA_HORAS", default=48)

# Desde cuando traer marcas la primera vez, si la base esta vacia.
SMARTPSS_FECHA_INICIO = env("SMARTPSS_FECHA_INICIO", default="")

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
