"""Ajustes para la suite de tests.

Base en memoria, hashing rápido y ninguna llamada real a Transbank.
"""
import dj_database_url
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False
TESTING = True

ALLOWED_HOSTS = ['*']

# Por defecto SQLite en memoria (rápido). Con TEST_DATABASE_URL la suite corre
# contra PostgreSQL real, igual que en Supabase: útil para CI o antes de un
# despliegue, porque SQLite no reproduce bloqueos ni restricciones de Postgres.
_test_database_url = config('TEST_DATABASE_URL', default='')
if _test_database_url:
    DATABASES = {'default': dj_database_url.parse(_test_database_url)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }

# Hashing rápido: los tests no evalúan la fortaleza del algoritmo.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Sin manifest para no depender de collectstatic.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Credenciales de integración: las pruebas de pago usan dobles de prueba y
# nunca contactan la API real.
TRANSBANK_ENVIRONMENT = 'integration'

SITE_URL = 'http://testserver'

# Silencia el ruido de logs durante los tests.
LOGGING['root']['level'] = 'CRITICAL'  # noqa: F405
for _logger in LOGGING['loggers'].values():  # noqa: F405
    _logger['level'] = 'CRITICAL'
