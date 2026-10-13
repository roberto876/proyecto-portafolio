"""Subida de imágenes de producto a Supabase Storage (opcional).

Sin configurar, el panel sigue funcionando con enlaces (URL) de imágenes. Con
``SUPABASE_URL`` y ``SUPABASE_SERVICE_ROLE_KEY`` definidas, el panel permite
subir archivos, que quedan en un bucket público con una URL permanente.

La clave de servicio solo se usa en el servidor y nunca llega al navegador.
El nombre del archivo lo genera el servidor: el usuario no controla la ruta.
"""
import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger('django')

UPLOAD_TIMEOUT_SECONDS = 20


class StorageError(Exception):
    """Fallo al subir una imagen, con mensaje comprensible para el usuario."""


def is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def detect_image_type(head: bytes) -> tuple[str, str] | None:
    """Identifica la imagen por su firma de bytes, no por la extensión.

    Un archivo renombrado a ``.jpg`` no pasa este control.
    """
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', 'jpg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', 'png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp', 'webp'
    return None


def public_url(path: str) -> str:
    """URL pública de un objeto en un bucket público de Supabase."""
    return (
        f'{settings.SUPABASE_URL}/storage/v1/object/public/'
        f'{settings.SUPABASE_STORAGE_BUCKET}/{path}'
    )


def _auth_headers() -> dict[str, str]:
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {'apikey': key}
    # La clave clásica «service_role» es un JWT y va también como Bearer. Las
    # claves nuevas («sb_secret_...») no son JWT y basta con «apikey».
    if key.startswith('eyJ'):
        headers['Authorization'] = f'Bearer {key}'
    return headers


def _explain(response) -> str:
    """Traduce la respuesta de error de Supabase a una instrucción concreta."""
    bucket = settings.SUPABASE_STORAGE_BUCKET
    text = response.text or ''
    if 'Bucket not found' in text or response.status_code == 404:
        return (f'No existe el bucket «{bucket}» en Supabase. Créalo en Storage > '
                'New bucket, con ese nombre exacto y marcado como «Public».')
    if response.status_code in (401, 403):
        return ('Supabase rechazó la clave. En Vercel, SUPABASE_SERVICE_ROLE_KEY debe '
                'ser la clave secreta (service_role), no la «anon/publishable».')
    if response.status_code == 413:
        return 'La foto es demasiado grande para Supabase. Redúcela e inténtalo de nuevo.'
    return f'Supabase respondió con un error ({response.status_code}). Inténtalo de nuevo.'


def upload_image(uploaded_file, *, folder: str = 'productos') -> str:
    """Sube una imagen y devuelve su URL pública.

    :raises StorageError: con un mensaje apto para mostrar en el formulario.
    """
    if not is_configured():
        raise StorageError(
            'La subida de fotos no está activada. Pega el enlace de la imagen, '
            'o actívala siguiendo GUIA.md, Parte 2, paso 7 (fotos).'
        )

    max_bytes = settings.MAX_IMAGE_UPLOAD_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise StorageError(
            f'La foto pesa más de {settings.MAX_IMAGE_UPLOAD_MB} MB. Redúcela '
            '(por ejemplo en squoosh.app) e inténtalo de nuevo.'
        )

    data = uploaded_file.read()
    kind = detect_image_type(data[:16])
    if kind is None:
        raise StorageError('El archivo no es una imagen JPG, PNG o WebP.')
    content_type, extension = kind

    path = f'{folder}/{uuid.uuid4().hex}.{extension}'
    endpoint = (
        f'{settings.SUPABASE_URL}/storage/v1/object/'
        f'{settings.SUPABASE_STORAGE_BUCKET}/{path}'
    )
    headers = {**_auth_headers(), 'Content-Type': content_type, 'x-upsert': 'false'}

    try:
        response = requests.post(
            endpoint, data=data, headers=headers, timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.exception('No se pudo conectar con Supabase Storage')
        raise StorageError(
            'No se pudo conectar con Supabase Storage. Inténtalo de nuevo en un momento.'
        ) from exc

    if response.status_code >= 400:
        logger.error('Supabase Storage respondió %s: %s',
                     response.status_code, (response.text or '')[:300])
        raise StorageError(_explain(response))

    return public_url(path)
