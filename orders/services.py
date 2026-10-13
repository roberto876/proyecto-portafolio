"""Servicios de órdenes e inventario.

Aquí vive toda la lógica que debe ser atómica: crear una orden, reservar
stock, liberarlo y descontarlo definitivamente. Las vistas no manipulan
inventario directamente.

Estrategia de inventario
------------------------
``ProductVariant.stock`` es el inventario físico y ``ProductVariant.reserved``
la parte comprometida por órdenes pendientes de pago. Lo vendible es la
diferencia entre ambos.

* Al crear la orden se **reserva** (``reserved += cantidad``).
* Si el pago se aprueba se **descuenta** (``stock -= cantidad`` y
  ``reserved -= cantidad``).
* Si el pago se rechaza, se cancela o expira, se **libera**
  (``reserved -= cantidad``).

Los flags ``Order.stock_reserved`` y ``Order.stock_committed`` garantizan que
cada transición ocurra como máximo una vez, incluso si Transbank llama dos
veces al callback.
"""
import logging
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from store.models import Product, ProductVariant

from .emails import send_order_paid_emails
from .models import Order, OrderItem, OrderStatus

logger = logging.getLogger('orders')


class OrderError(Exception):
    """Error de negocio al procesar una orden."""


class InsufficientStockError(OrderError):
    """No hay stock suficiente para alguna de las líneas."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__(' '.join(issues))


def _lock_variants(variant_ids: list[int]) -> dict[int, ProductVariant]:
    """Bloquea las variantes indicadas para actualización.

    Se ordena por clave primaria para que dos transacciones concurrentes
    tomen los bloqueos en el mismo orden y no se produzcan interbloqueos.
    """
    variants = (
        ProductVariant.objects
        .select_for_update()
        .select_related('product')
        .filter(pk__in=sorted(variant_ids))
        .order_by('pk')
    )
    return {variant.pk: variant for variant in variants}


@transaction.atomic
def create_order_from_cart(*, cart, data: dict, user=None) -> Order:
    """Crea una orden a partir del carrito y reserva su stock.

    Todo ocurre dentro de una única transacción: o se crea la orden con su
    stock reservado, o no se modifica nada.

    :param cart: instancia de ``cart.cart.Cart``.
    :param data: datos ya validados del formulario de checkout.
    :param user: usuario autenticado, o ``None`` para compra de invitado.
    :raises OrderError: si el carrito está vacío.
    :raises InsufficientStockError: si alguna línea no tiene stock.
    """
    items = cart.items
    if not items:
        raise OrderError('Tu carrito está vacío.')

    locked = _lock_variants([item.variant.pk for item in items])

    # Validación de stock contra las filas ya bloqueadas: entre que el cliente
    # vio el carrito y llegó aquí, otro comprador pudo llevarse las unidades.
    issues: list[str] = []
    for item in items:
        variant = locked.get(item.variant.pk)
        if variant is None or not variant.is_active:
            issues.append(f'{item.product.name} ya no está disponible.')
            continue
        if variant.available_stock < item.quantity:
            issues.append(
                f'{item.product.name} ({variant.label}): quedan '
                f'{variant.available_stock} unidades y pediste {item.quantity}.'
            )
    if issues:
        raise InsufficientStockError(issues)

    # Los importes se recalculan aquí desde la base de datos. El navegador no
    # participa en el cálculo del monto a cobrar.
    subtotal = sum(item.subtotal for item in items)
    shipping_cost = cart.shipping_cost
    total = subtotal + shipping_cost

    order = Order.objects.create(
        user=user if (user and user.is_authenticated) else None,
        customer_first_name=data['first_name'],
        customer_last_name=data['last_name'],
        customer_email=data['email'],
        customer_phone=data['phone'],
        shipping_region=data['region'],
        shipping_commune=data['commune'],
        shipping_address=data['address'],
        shipping_number=data['address_number'],
        shipping_extra=data.get('extra', ''),
        subtotal=subtotal,
        shipping_cost=shipping_cost,
        total=total,
        status=OrderStatus.PENDING_PAYMENT,
    )

    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product=item.product,
            variant=item.variant,
            product_name=item.product.name,
            sku=item.variant.sku,
            size=item.variant.get_size_display(),
            color=item.variant.color,
            image=item.product.main_image,
            unit_price=item.unit_price,
            quantity=item.quantity,
            subtotal=item.subtotal,
        )
        for item in items
    ])

    # Reserva del stock sobre las mismas filas ya bloqueadas.
    for item in items:
        ProductVariant.objects.filter(pk=item.variant.pk).update(
            reserved=F('reserved') + item.quantity,
        )

    order.stock_reserved = True
    order.save(update_fields=['stock_reserved', 'updated_at'])

    logger.info(
        'Orden %s creada (total=%s, lineas=%s, usuario=%s)',
        order.order_number, total, len(items),
        order.user_id or 'invitado',
    )
    return order


@transaction.atomic
def reserve_stock(order: Order) -> bool:
    """Vuelve a reservar el stock de una orden pendiente. Idempotente.

    Se usa al reintentar el pago de una orden rechazada o expirada, cuya
    reserva ya se había liberado. Vuelve a comprobar la disponibilidad: entre
    el intento fallido y el nuevo, otro comprador pudo llevarse las unidades.

    :return: ``True`` si esta llamada reservó el stock.
    :raises InsufficientStockError: si ya no hay unidades suficientes.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.stock_committed or locked.stock_reserved:
        return False

    items = list(locked.items.select_related('variant'))
    variants = _lock_variants([i.variant_id for i in items if i.variant_id])

    issues: list[str] = []
    for item in items:
        variant = variants.get(item.variant_id) if item.variant_id else None
        if variant is None or not variant.is_active:
            issues.append(f'{item.product_name} ya no está disponible.')
        elif variant.available_stock < item.quantity:
            issues.append(
                f'{item.product_name} ({item.size}/{item.color}): quedan '
                f'{variant.available_stock} unidades y pediste {item.quantity}.'
            )
    if issues:
        raise InsufficientStockError(issues)

    for item in items:
        if item.variant_id:
            ProductVariant.objects.filter(pk=item.variant_id).update(
                reserved=F('reserved') + item.quantity,
            )

    locked.stock_reserved = True
    locked.save(update_fields=['stock_reserved', 'updated_at'])

    order.refresh_from_db()
    logger.info('Stock re-reservado para la orden %s', locked.order_number)
    return True


@transaction.atomic
def release_stock(order: Order) -> bool:
    """Libera la reserva de stock de una orden. Idempotente.

    :return: ``True`` si esta llamada liberó el stock, ``False`` si ya estaba
        liberado (o nunca se reservó).
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not order.stock_reserved or order.stock_committed:
        return False

    for item in order.items.select_related('variant'):
        if item.variant_id is None:
            continue
        # `Greatest` no es necesario: el flag garantiza una sola liberación,
        # pero se acota a 0 por seguridad ante datos inconsistentes previos.
        ProductVariant.objects.filter(
            pk=item.variant_id, reserved__gte=item.quantity,
        ).update(reserved=F('reserved') - item.quantity)

    order.stock_reserved = False
    order.save(update_fields=['stock_reserved', 'updated_at'])
    logger.info('Stock liberado para la orden %s', order.order_number)
    return True


@transaction.atomic
def commit_stock(order: Order) -> bool:
    """Descuenta definitivamente el stock de una orden pagada. Idempotente.

    :return: ``True`` si esta llamada descontó el stock, ``False`` si ya se
        había descontado antes.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.stock_committed:
        return False

    for item in order.items.select_related('variant'):
        if item.variant_id is None:
            continue
        if order.stock_reserved:
            # Convierte la reserva en venta en una sola sentencia atómica.
            ProductVariant.objects.filter(pk=item.variant_id).update(
                stock=F('stock') - item.quantity,
                reserved=F('reserved') - item.quantity,
            )
        else:
            ProductVariant.objects.filter(pk=item.variant_id).update(
                stock=F('stock') - item.quantity,
            )
        if item.product_id:
            Product.objects.filter(pk=item.product_id).update(
                sales_count=F('sales_count') + item.quantity,
            )

    order.stock_reserved = False
    order.stock_committed = True
    order.save(update_fields=['stock_reserved', 'stock_committed', 'updated_at'])
    logger.info('Stock descontado para la orden %s', order.order_number)
    return True


@transaction.atomic
def mark_as_paid(order: Order) -> bool:
    """Marca la orden como pagada y descuenta el stock. Idempotente.

    Nunca debe llamarse a partir de información enviada por el navegador:
    solo tras confirmar la transacción contra Transbank.

    :return: ``True`` si esta llamada cambió el estado de la orden.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.is_paid:
        logger.info('Orden %s ya estaba pagada; se ignora', locked.order_number)
        return False

    locked.status = OrderStatus.PAID
    locked.paid_at = timezone.now()
    locked.save(update_fields=['status', 'paid_at', 'updated_at'])

    commit_stock(locked)

    # Los correos salen solo si la transacción se confirma: nunca se avisa
    # de una venta que finalmente se revirtió.
    transaction.on_commit(partial(send_order_paid_emails, locked.pk))

    order.refresh_from_db()
    logger.info('Orden %s marcada como pagada', locked.order_number)
    return True


@transaction.atomic
def mark_as_rejected(order: Order) -> bool:
    """Marca la orden como rechazada y libera el stock reservado."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REJECTED):
        return False

    changed = locked.status != OrderStatus.PAYMENT_REJECTED
    locked.status = OrderStatus.PAYMENT_REJECTED
    locked.save(update_fields=['status', 'updated_at'])
    release_stock(locked)

    order.refresh_from_db()
    if changed:
        logger.info('Orden %s marcada como rechazada', locked.order_number)
    return changed


@transaction.atomic
def mark_as_cancelled(order: Order) -> bool:
    """Cancela la orden y libera el stock reservado."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.is_paid or locked.status == OrderStatus.CANCELLED:
        return False

    locked.status = OrderStatus.CANCELLED
    locked.save(update_fields=['status', 'updated_at'])
    release_stock(locked)

    order.refresh_from_db()
    logger.info('Orden %s cancelada', locked.order_number)
    return True


# ---------------------------------------------------------------------------
# Órdenes abandonadas
# ---------------------------------------------------------------------------
#: Tope de órdenes procesadas por barrido, para acotar la duración.
SWEEP_BATCH_SIZE = 200
#: Segundos mínimos entre barridos oportunistas en una misma instancia.
SWEEP_THROTTLE_SECONDS = 60
SWEEP_CACHE_KEY = 'orders:last-expired-sweep'


def release_expired_orders(*, older_than_minutes: int | None = None) -> int:
    """Cancela las órdenes abandonadas y devuelve su stock a la venta.

    Una orden se considera abandonada si lleva más de
    ``ORDER_RESERVATION_MINUTES`` sin pagarse ni moverse. Nunca se toca una
    orden cuyo pago se está confirmando, ni una con un intento de pago
    reciente (el comprador podría estar en el formulario de Webpay).

    Es idempotente: ejecutarla dos veces seguidas no tiene efecto adicional,
    tal como recomienda Vercel para las tareas programadas.

    :return: número de órdenes canceladas.
    """
    minutes = (
        settings.ORDER_RESERVATION_MINUTES
        if older_than_minutes is None else older_than_minutes
    )
    cutoff = timezone.now() - timedelta(minutes=minutes)

    candidates = (
        Order.objects
        .filter(
            status=OrderStatus.PENDING_PAYMENT,
            stock_reserved=True,
            # updated_at y no created_at: al reintentar un pago la orden se
            # reactiva y no debe cancelarse mientras el cliente paga.
            updated_at__lt=cutoff,
        )
        .exclude(payments__status='PROCESSING')
        .exclude(payments__created_at__gte=cutoff)
        .values_list('pk', flat=True)
        .distinct()
    )

    released = 0
    for pk in list(candidates[:SWEEP_BATCH_SIZE]):
        if mark_as_cancelled(Order(pk=pk)):
            released += 1

    if released:
        logger.info('Se liberaron las reservas de %s orden(es) abandonada(s)', released)
    return released


def maybe_release_expired_orders() -> int:
    """Barrido oportunista, limitado a uno por minuto por instancia.

    El cron del plan gratuito de Vercel corre una sola vez al día, así que se
    aprovecha el tráfico normal de la tienda para que las unidades de un
    carrito abandonado vuelvan a estar a la venta sin esperar al día
    siguiente. Un fallo aquí nunca debe impedir que la página cargue.
    """
    if not cache.add(SWEEP_CACHE_KEY, True, timeout=SWEEP_THROTTLE_SECONDS):
        return 0
    try:
        return release_expired_orders()
    except Exception:  # noqa: BLE001 - el barrido es secundario a la página.
        logger.exception('Falló el barrido de órdenes abandonadas')
        return 0
