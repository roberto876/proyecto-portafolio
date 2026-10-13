"""Chequeos de estado de la tienda, en lenguaje de dueño de negocio.

Cada chequeo dice qué pasa y, si algo falta, qué hacer. Alimenta la página
«Estado de la tienda» del panel de administración.
"""
from dataclasses import dataclass

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F

OK, WARNING, ERROR, INFO = 'ok', 'warning', 'error', 'info'


@dataclass(frozen=True)
class Check:
    """Resultado de un chequeo."""

    title: str
    level: str
    message: str
    fix: str = ''


def _database() -> Check:
    try:
        connection.ensure_connection()
    except Exception:  # noqa: BLE001
        return Check('Base de datos', ERROR, 'La tienda no logra conectarse a la base de datos.',
                     'Revisa la variable DATABASE_URL en Vercel (GUIA.md, Parte 2, paso 5).')
    return Check('Base de datos', OK, 'Conectada y respondiendo.')


def _migrations() -> Check:
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception:  # noqa: BLE001
        return Check('Estructura de datos', WARNING, 'No se pudo comprobar.')
    if pending:
        return Check('Estructura de datos', ERROR,
                     f'Faltan {len(pending)} actualizaciones de la base de datos.',
                     'En tu computador ejecuta: python manage.py preparar_produccion')
    return Check('Estructura de datos', OK, 'Al día.')


def _payments() -> Check:
    if settings.TRANSBANK_ENVIRONMENT == 'production':
        return Check('Pagos', OK, 'Webpay en PRODUCCIÓN: los pagos son reales.')
    return Check('Pagos', WARNING,
                 'Webpay en modo PRUEBA: los pagos son simulados y no llega dinero.',
                 'Para cobrar de verdad sigue GUIA.md, Parte 3 «Vender de verdad».')


def _email() -> Check:
    backend = settings.EMAIL_BACKEND.rsplit('.', 2)[-2]
    if backend == 'smtp':
        return Check('Correos', OK, 'Configurados: se envían confirmaciones y avisos de venta.')
    return Check('Correos', WARNING,
                 'Los correos NO se están enviando (confirmaciones, avisos, recuperar contraseña).',
                 'Actívalos siguiendo GUIA.md, Parte 2, paso 8 (correos).')


def _images() -> Check:
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
        return Check('Fotos de productos', OK, 'Puedes subir fotos directamente desde el panel.')
    return Check('Fotos de productos', WARNING,
                 'Solo puedes usar enlaces (URL) de imágenes, no subir archivos.',
                 'Actívala siguiendo GUIA.md, Parte 2, paso 7 (fotos).')


def _cron() -> Check:
    if settings.CRON_SECRET:
        return Check('Tareas automáticas', OK, 'Activas: cada día se liberan carritos abandonados.')
    return Check('Tareas automáticas', WARNING,
                 'Desactivadas. Los carritos abandonados se liberan igual al navegar la tienda.',
                 'Agrega la variable CRON_SECRET en Vercel (la genera el asistente).')


def _store_info(store) -> list[Check]:
    checks = []
    if store.has_legal_info:
        checks.append(Check('Datos legales', OK, f'{store.legal_name} · RUT {store.rut}'))
    else:
        checks.append(Check('Datos legales', WARNING,
                            'Falta la razón social y/o el RUT. La ley exige mostrarlos al vender online.',
                            'Complétalos en «Ajustes de la tienda».'))
    if store.contact_email:
        checks.append(Check('Email de la tienda', OK, f'Los avisos de venta llegan a {store.contact_email}.'))
    else:
        checks.append(Check('Email de la tienda', WARNING,
                            'No hay email configurado: no recibirás avisos de nuevas ventas.',
                            'Agrégalo en «Ajustes de la tienda».'))
    return checks


def _operations() -> list[Check]:
    from orders.models import Order, OrderStatus
    from store.models import Product, ProductVariant

    checks = []
    products = Product.objects.active().count()
    if products:
        checks.append(Check('Catálogo', OK, f'{products} producto(s) publicados.'))
    else:
        checks.append(Check('Catálogo', WARNING, 'Aún no hay productos publicados.',
                            'Crea el primero en Tienda > Productos > Añadir.'))

    to_ship = Order.objects.filter(status__in=[OrderStatus.PAID, OrderStatus.PROCESSING]).count()
    checks.append(Check(
        'Pedidos por despachar', INFO if to_ship else OK,
        f'{to_ship} pedido(s) pagados esperando despacho.' if to_ship else 'No hay pedidos pendientes.',
        'Revísalos en Órdenes, filtrando por estado «Pagada».' if to_ship else '',
    ))

    low = (
        ProductVariant.objects.active()
        .filter(product__is_active=True, stock__lte=F('reserved') + 3)
        .count()
    )
    checks.append(Check(
        'Stock bajo', INFO if low else OK,
        f'{low} variante(s) con 3 unidades o menos.' if low else 'Sin variantes con stock bajo.',
        'Revísalas en Tienda > Variantes, filtro «Stock bajo».' if low else '',
    ))
    return checks


def run_checks() -> list[Check]:
    """Ejecuta todos los chequeos, del más crítico al informativo."""
    database = _database()
    if database.level == ERROR:
        return [database]

    from store.models import StoreSettings

    return [
        database,
        _migrations(),
        _payments(),
        _email(),
        *_store_info(StoreSettings.load()),
        _images(),
        _cron(),
        *_operations(),
    ]


def summary(checks: list[Check]) -> str:
    """Estado global: el peor nivel encontrado."""
    levels = {check.level for check in checks}
    if ERROR in levels:
        return ERROR
    if WARNING in levels:
        return WARNING
    return OK
