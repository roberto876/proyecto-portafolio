"""
Configuración base compartida por todos los ambientes.

Los valores sensibles se leen exclusivamente desde variables de entorno.
Nunca se debe escribir un secreto real en este archivo.
"""
from pathlib import Path

import dj_database_url
from decouple import Csv, config

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Seguridad base
# ---------------------------------------------------------------------------
# En producción SECRET_KEY es obligatoria (ver settings/production.py).
SECRET_KEY = config('SECRET_KEY', default='django-insecure-solo-para-desarrollo-local')
DEBUG = False
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

# ---------------------------------------------------------------------------
# Aplicaciones
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django.contrib.humanize',
    # Apps del proyecto
    'store.apps.StoreConfig',
    'accounts.apps.AccountsConfig',
    'cart.apps.CartConfig',
    'orders.apps.OrdersConfig',
    'payments.apps.PaymentsConfig',
    'ops.apps.OpsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.store_context',
                'cart.context_processors.cart_context',
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# DATABASE_URL apunta a PostgreSQL (Supabase) en producción. En desarrollo, si
# no se define, se usa SQLite para poder levantar el proyecto sin
# infraestructura externa.
DATABASE_URL = config('DATABASE_URL', default='').strip()

if DATABASE_URL:
    from django.core.exceptions import ImproperlyConfigured

    # Los dos errores más probables al copiar la dirección desde Supabase se
    # detectan aquí, antes de que el parser falle con un traceback en inglés.
    if '[YOUR-PASSWORD]' in DATABASE_URL:
        raise ImproperlyConfigured(
            'DATABASE_URL todavía tiene el texto [YOUR-PASSWORD]. Reemplázalo '
            '(incluidos los corchetes) por la contraseña de tu base de datos de Supabase.'
        )

    # SSL solo tiene sentido en PostgreSQL; aplicado a SQLite rompería la
    # conexión.
    _is_postgres = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
    try:
        _default_db = dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=config('DB_CONN_MAX_AGE', default=0, cast=int),
            conn_health_checks=True,
            ssl_require=_is_postgres and config('DB_SSL_REQUIRE', default=True, cast=bool),
        )
    except ValueError as exc:  # dj_database_url.ParseError hereda de ValueError.
        raise ImproperlyConfigured(
            'DATABASE_URL no es una dirección válida. Cópiala de nuevo desde '
            'Supabase (Connect > Transaction pooler). Si tu contraseña tiene '
            'símbolos como @ # / ? o %, cámbiala en Supabase por una con solo '
            'letras y números.'
        ) from exc
    DATABASES = {'default': _default_db}
    if _is_postgres:
        # El pooler de Supabase en modo transacción no admite cursores del
        # lado del servidor (lo exige la documentación de Django). Se aplica
        # también en local porque el asistente de despliegue migra Supabase
        # desde el equipo del cliente con esta configuración.
        DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'store:home'
LOGOUT_REDIRECT_URL = 'store:home'

# ---------------------------------------------------------------------------
# Internacionalización
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Archivos estáticos y media
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Las imágenes de producto se almacenan como URL absolutas (CDN / Supabase
# Storage). El filesystem local nunca se usa como almacenamiento persistente.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------------------------------------------------------------------------
# Sesiones y cookies
# ---------------------------------------------------------------------------
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 días
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
# El token CSRF debe ser legible desde JavaScript para las peticiones fetch().
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

# ---------------------------------------------------------------------------
# Reglas de negocio de la tienda
# ---------------------------------------------------------------------------
SITE_NAME = 'GYMFORGE'
SITE_URL = config('SITE_URL', default='http://localhost:8000')

CART_SESSION_KEY = 'cart'
CART_MAX_QUANTITY_PER_ITEM = 10   # Tope de unidades por línea
CART_MAX_DISTINCT_ITEMS = 30      # Tope de líneas distintas

FREE_SHIPPING_THRESHOLD = config('FREE_SHIPPING_THRESHOLD', default=60000, cast=int)
SHIPPING_COST = config('SHIPPING_COST', default=4990, cast=int)

PRODUCTS_PER_PAGE = 12

# ---------------------------------------------------------------------------
# Transbank Webpay Plus
# ---------------------------------------------------------------------------
# Credenciales públicas del ambiente de integración publicadas por Transbank.
# Solo aplican como valor por defecto en desarrollo: producción exige las
# credenciales reales vía variables de entorno (ver settings/production.py).
TRANSBANK_ENVIRONMENT = config('TRANSBANK_ENVIRONMENT', default='integration')
TRANSBANK_COMMERCE_CODE = config('TRANSBANK_COMMERCE_CODE', default='597055555532')
TRANSBANK_API_KEY = config(
    'TRANSBANK_API_KEY',
    default='579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C',
)
# Menor que el maxDuration de la función en Vercel (30 s): si Transbank no
# responde, la tienda muestra un error amable en vez de cortarse de golpe.
TRANSBANK_TIMEOUT = config('TRANSBANK_TIMEOUT', default=20, cast=int)

# ---------------------------------------------------------------------------
# Operación de la tienda
# ---------------------------------------------------------------------------
# Minutos que una orden sin pagar mantiene reservado su stock. Pasado ese
# plazo se cancela sola y las unidades vuelven a estar a la venta.
ORDER_RESERVATION_MINUTES = config('ORDER_RESERVATION_MINUTES', default=30, cast=int)

# Validez del enlace firmado para ver una orden (vuelta de Webpay y correo
# de confirmación). 30 días, como el seguimiento típico de un pedido.
PAYMENT_ACCESS_MAX_AGE = 60 * 60 * 24 * 30

# Secreto que Vercel envía al llamar a las tareas programadas (cron).
# Si está vacío, el endpoint de tareas queda desactivado.
CRON_SECRET = config('CRON_SECRET', default='')

# ---------------------------------------------------------------------------
# Supabase Storage (opcional): subir fotos desde el panel de administración
# ---------------------------------------------------------------------------
# Sin estas variables el admin sigue funcionando pegando URLs de imágenes.
# La clave de servicio se usa SOLO en el servidor; nunca llega al navegador.
SUPABASE_URL = config('SUPABASE_URL', default='').rstrip('/')
SUPABASE_SERVICE_ROLE_KEY = config('SUPABASE_SERVICE_ROLE_KEY', default='')
SUPABASE_STORAGE_BUCKET = config('SUPABASE_STORAGE_BUCKET', default='productos')
# Vercel rechaza cualquier petición de más de 4,5 MB: el tope deja margen.
MAX_IMAGE_UPLOAD_MB = 4

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@gymforge.cl')
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ---------------------------------------------------------------------------
# Content Security Policy (aplicada por config.middleware)
# ---------------------------------------------------------------------------
CSP_DIRECTIVES = {
    'default-src': ["'self'"],
    # Sin 'unsafe-inline': esta es la directiva que realmente frena el XSS.
    # Ningún script se ejecuta desde el HTML ni desde dominios de terceros.
    'script-src': ["'self'"],
    # Los estilos en línea sí se permiten. Valores como el color de cada
    # variante o el ancho de la barra de progreso salen de la base de datos y
    # no pueden vivir en una hoja estática; además, los hashes y nonces del
    # CSP no aplican a los atributos `style`. El riesgo residual de
    # 'unsafe-inline' en estilos es marginal comparado con el de scripts.
    'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
    'font-src': ["'self'", 'https://fonts.gstatic.com', 'data:'],
    # Las imágenes de producto se sirven desde CDNs externas.
    'img-src': ["'self'", 'data:', 'https:'],
    'connect-src': ["'self'"],
    # Webpay se abre por redirección completa, nunca embebido.
    'frame-ancestors': ["'none'"],
    'form-action': [
        "'self'",
        'https://webpay3g.transbank.cl',
        'https://webpay3gint.transbank.cl',
    ],
    'base-uri': ["'self'"],
    'object-src': ["'none'"],
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'payments': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'orders': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'cart': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
