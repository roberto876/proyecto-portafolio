"""Ajustes de producción (Vercel + Supabase).

Este módulo falla de forma explícita si falta una variable crítica: es
preferible que el despliegue se caiga a que arranque de forma insegura.
"""
import os

from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, TRANSBANK_ENVIRONMENT

DEBUG = False

# ---------------------------------------------------------------------------
# Variables obligatorias
# ---------------------------------------------------------------------------
# Los mensajes están pensados para quien administra la tienda sin ser
# programador: dicen qué falta y dónde se arregla. Aparecen en el registro de
# construcción (Build Logs) de Vercel.
_GUIDE = 'Revisa GUIA.md, Parte 2, paso 5 (variables de entorno en Vercel).'

SECRET_KEY = config('SECRET_KEY', default='')
if not SECRET_KEY or SECRET_KEY.startswith('django-insecure'):
    raise ImproperlyConfigured(
        'FALTA SECRET_KEY. La tienda no arranca sin su clave secreta. '
        'La genera por ti el comando "python manage.py preparar_produccion" '
        f'(archivo vercel-env.txt). {_GUIDE}'
    )

_database_url = config('DATABASE_URL', default='')
if not _database_url:
    raise ImproperlyConfigured(
        'FALTA DATABASE_URL. La tienda necesita la dirección de la base de '
        f'datos de Supabase. {_GUIDE}'
    )

# En producción real (no integración) las credenciales de Transbank son
# obligatorias: los valores por defecto son los públicos de integración.
if TRANSBANK_ENVIRONMENT == 'production':
    for _var in ('TRANSBANK_COMMERCE_CODE', 'TRANSBANK_API_KEY'):
        if not config(_var, default=''):
            raise ImproperlyConfigured(
                f'FALTA {_var}. Pusiste TRANSBANK_ENVIRONMENT=production pero '
                'no las credenciales reales que te entregó Transbank. Revisa '
                'GUIA.md, Parte 3, punto 3 (contratar Webpay Plus).'
            )

# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------
# Vercel publica tres dominios, todos sin esquema:
#   VERCEL_PROJECT_PRODUCTION_URL  dominio estable (tu-tienda.vercel.app o el
#                                  dominio propio más corto). Es el que visita
#                                  la gente: sin él, la tienda responde 400.
#   VERCEL_URL                     URL única de cada despliegue.
#   VERCEL_BRANCH_URL              URL de la rama (previews).
# Se añaden solos, así que en Vercel no hace falta definir ALLOWED_HOSTS.
_vercel_hosts = [
    os.environ.get(name, '').strip()
    for name in ('VERCEL_PROJECT_PRODUCTION_URL', 'VERCEL_URL', 'VERCEL_BRANCH_URL')
]
_vercel_hosts = [host for host in _vercel_hosts if host]

ALLOWED_HOSTS = [host for host in ALLOWED_HOSTS if host]
for _host in _vercel_hosts:
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

CSRF_TRUSTED_ORIGINS = [origin for origin in CSRF_TRUSTED_ORIGINS if origin]
for _host in _vercel_hosts:
    _origin = f'https://{_host}'
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

# Dominios propios declarados en ALLOWED_HOSTS también son orígenes de confianza.
for _host in ALLOWED_HOSTS:
    if _host.startswith('.') or _host in ('localhost', '127.0.0.1'):
        continue
    _origin = f'https://{_host}'
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

# URL pública para enlaces absolutos (correos). Si no se define, se usa el
# dominio de producción que informa Vercel.
if not config('SITE_URL', default='') and os.environ.get('VERCEL_PROJECT_PRODUCTION_URL'):
    SITE_URL = f"https://{os.environ['VERCEL_PROJECT_PRODUCTION_URL'].strip()}"

# ---------------------------------------------------------------------------
# HTTPS y cabeceras de seguridad
# ---------------------------------------------------------------------------
# Vercel termina TLS en el edge y propaga el esquema en X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)

SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# En entorno serverless conviene no reutilizar conexiones entre invocaciones:
# el pooler de Supabase (puerto 6543) gestiona el pool por nosotros.
DATABASES['default']['CONN_MAX_AGE'] = config(  # noqa: F405
    'DB_CONN_MAX_AGE', default=0, cast=int
)
# El pooler en modo transacción devuelve la conexión al pool tras cada
# transacción, así que un cursor del lado del servidor podría quedar huérfano
# en otra sesión. La documentación de Django exige desactivarlos.
# (Los prepared statements, que ese modo tampoco admite, ya los desactiva
# Django 5.2 por defecto con psycopg 3.)
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True  # noqa: F405

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
if config('EMAIL_HOST', default=''):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = config('EMAIL_HOST')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=False, cast=bool)
    # Un servidor de correo lento no debe dejar colgada la vuelta de Webpay.
    EMAIL_TIMEOUT = 10
else:
    # Sin SMTP configurado se descartan los correos en lugar de romper la app.
    EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING['root']['level'] = config('LOG_LEVEL', default='WARNING')  # noqa: F405
LOGGING['loggers']['django']['level'] = config('LOG_LEVEL', default='WARNING')  # noqa: F405
