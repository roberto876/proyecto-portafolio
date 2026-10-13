"""Selector de configuración por ambiente.

El ambiente se elige con la variable de entorno ``DJANGO_ENV``:

* ``development`` (por defecto en local)
* ``testing``
* ``production``

En Vercel basta con definir ``DJANGO_ENV=production`` en las variables del
proyecto; ``manage.py`` y ``wsgi.py`` apuntan siempre a ``config.settings``.
"""
import os

# Vercel define automáticamente VERCEL=1 en build y en runtime, así que un
# despliegue nunca arranca por accidente en modo desarrollo.
_default_env = 'production' if os.environ.get('VERCEL') else 'development'
DJANGO_ENV = os.environ.get('DJANGO_ENV', _default_env).strip().lower()

if DJANGO_ENV == 'production':
    from .production import *  # noqa: F401,F403
elif DJANGO_ENV == 'testing':
    from .testing import *  # noqa: F401,F403
elif DJANGO_ENV == 'development':
    from .development import *  # noqa: F401,F403
else:
    raise ValueError(
        f'DJANGO_ENV inválido: {DJANGO_ENV!r}. '
        'Valores permitidos: development, testing, production.'
    )
