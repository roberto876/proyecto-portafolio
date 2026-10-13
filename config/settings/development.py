"""Ajustes para desarrollo local.

Prioriza la comodidad de trabajo sin relajar nada que importe en producción:
las cookies siguen siendo HttpOnly y el CSP sigue activo.
"""
from decouple import Csv, config

from .base import *  # noqa: F401,F403
from .base import CSRF_TRUSTED_ORIGINS

DEBUG = True

ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1,0.0.0.0,testserver',
    cast=Csv(),
)

# Orígenes locales habituales, además de los definidos por el usuario.
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        CSRF_TRUSTED_ORIGINS
        + ['http://localhost:8000', 'http://127.0.0.1:8000']
    )
)

# En HTTP local las cookies seguras no viajarían.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Los correos (recuperación de contraseña) se imprimen en consola.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# WhiteNoise sirve los estáticos sin manifest para no requerir collectstatic.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
