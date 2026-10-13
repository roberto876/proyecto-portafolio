"""Modelos de órdenes.

Una orden es un documento histórico: sus líneas guardan una copia del nombre,
SKU y precio del producto en el momento de la compra, de modo que cambiar el
catálogo más adelante no altera lo que el cliente pagó.
"""
import secrets
from datetime import date

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from store.models import format_clp


class OrderStatus(models.TextChoices):
    """Estados posibles de una orden."""

    PENDING_PAYMENT = 'PENDING_PAYMENT', 'Pendiente de pago'
    PAID = 'PAID', 'Pagada'
    # Cubre rechazo del banco, anulación en Webpay y expiración del
    # formulario. En los tres casos la orden admite reintentar el pago.
    PAYMENT_REJECTED = 'PAYMENT_REJECTED', 'Pago no completado'
    CANCELLED = 'CANCELLED', 'Cancelada'
    PROCESSING = 'PROCESSING', 'En preparación'
    SHIPPED = 'SHIPPED', 'Enviada'
    DELIVERED = 'DELIVERED', 'Entregada'
    REFUNDED = 'REFUNDED', 'Reembolsada'


#: Estados en los que la orden ya no puede volver a intentar el pago.
CLOSED_STATUSES = frozenset({
    OrderStatus.PAID,
    OrderStatus.PROCESSING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.REFUNDED,
    OrderStatus.CANCELLED,
})

#: Estados que representan una compra efectivamente pagada.
PAID_STATUSES = frozenset({
    OrderStatus.PAID,
    OrderStatus.PROCESSING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
})


def generate_order_number() -> str:
    """Genera un identificador único y difícil de adivinar para la orden.

    El formato ``GF20260908A1B2C3D4`` ocupa 18 caracteres, dentro del límite
    de 26 que Transbank impone al campo ``buy_order``. La parte aleatoria
    tiene 32 bits: como la fecha es predecible, con menos entropía el número
    se podría adivinar por fuerza bruta.
    """
    return f'GF{date.today():%Y%m%d}{secrets.token_hex(4).upper()}'


class Order(models.Model):
    """Cabecera de una orden de compra."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
        verbose_name='Usuario',
        help_text='Vacío si la compra se hizo como invitado.',
    )
    order_number = models.CharField(
        'Número de orden', max_length=26, unique=True,
        default=generate_order_number, editable=False,
    )
    status = models.CharField(
        'Estado', max_length=20,
        choices=OrderStatus.choices, default=OrderStatus.PENDING_PAYMENT,
    )

    # Datos del comprador (copia histórica, independiente del perfil).
    customer_first_name = models.CharField('Nombre', max_length=100)
    customer_last_name = models.CharField('Apellido', max_length=100)
    customer_email = models.EmailField('Email', max_length=150)
    customer_phone = models.CharField('Teléfono', max_length=20)

    # Dirección de despacho.
    shipping_region = models.CharField('Región', max_length=100)
    shipping_commune = models.CharField('Comuna', max_length=100)
    shipping_address = models.CharField('Dirección', max_length=200)
    shipping_number = models.CharField('Número', max_length=20)
    shipping_extra = models.CharField(
        'Información adicional', max_length=200, blank=True,
        help_text='Departamento, oficina, referencias de entrega.',
    )

    # Importes en pesos chilenos, calculados siempre en el servidor.
    subtotal = models.PositiveIntegerField('Subtotal', validators=[MinValueValidator(0)])
    shipping_cost = models.PositiveIntegerField('Costo de despacho', default=0)
    total = models.PositiveIntegerField('Total', validators=[MinValueValidator(1)])

    # Control del inventario asociado a esta orden. Ambos flags hacen que
    # reservar, liberar y descontar sean operaciones idempotentes.
    stock_reserved = models.BooleanField('Stock reservado', default=False)
    stock_committed = models.BooleanField('Stock descontado', default=False)

    created_at = models.DateTimeField('Creada', auto_now_add=True)
    updated_at = models.DateTimeField('Actualizada', auto_now=True)
    paid_at = models.DateTimeField('Pagada el', null=True, blank=True)

    class Meta:
        verbose_name = 'Orden'
        verbose_name_plural = 'Órdenes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['customer_email']),
        ]

    def __str__(self):
        return f'Orden {self.order_number}'

    def get_absolute_url(self):
        return reverse('orders:detail', kwargs={'order_number': self.order_number})

    # -- Datos derivados ----------------------------------------------------
    @property
    def customer_full_name(self) -> str:
        return f'{self.customer_first_name} {self.customer_last_name}'.strip()

    @property
    def full_shipping_address(self) -> str:
        parts = [f'{self.shipping_address} {self.shipping_number}'.strip()]
        if self.shipping_extra:
            parts.append(self.shipping_extra)
        parts.append(f'{self.shipping_commune}, {self.shipping_region}')
        return ', '.join(p for p in parts if p)

    @property
    def total_formatted(self) -> str:
        return format_clp(self.total)

    @property
    def subtotal_formatted(self) -> str:
        return format_clp(self.subtotal)

    @property
    def shipping_cost_formatted(self) -> str:
        return 'Gratis' if self.shipping_cost == 0 else format_clp(self.shipping_cost)

    @property
    def total_units(self) -> int:
        return sum(item.quantity for item in self.items.all())

    # -- Estado -------------------------------------------------------------
    @property
    def is_paid(self) -> bool:
        return self.status in PAID_STATUSES

    @property
    def is_pending_payment(self) -> bool:
        return self.status == OrderStatus.PENDING_PAYMENT

    @property
    def can_retry_payment(self) -> bool:
        """Solo se puede reintentar mientras la orden no esté cerrada."""
        return self.status not in CLOSED_STATUSES



class OrderItem(models.Model):
    """Línea de una orden, con los datos del producto congelados."""

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items', verbose_name='Orden',
    )
    # Referencias débiles: si el catálogo cambia, la orden sigue siendo legible.
    product = models.ForeignKey(
        'store.Product', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_items', verbose_name='Producto',
    )
    variant = models.ForeignKey(
        'store.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_items', verbose_name='Variante',
    )

    # Copia histórica de los datos del producto.
    product_name = models.CharField('Nombre del producto', max_length=300)
    sku = models.CharField('SKU', max_length=80)
    size = models.CharField('Talla', max_length=20)
    color = models.CharField('Color', max_length=50)
    image = models.URLField('Imagen', max_length=500, blank=True)
    unit_price = models.PositiveIntegerField('Precio unitario')
    quantity = models.PositiveIntegerField('Cantidad', validators=[MinValueValidator(1)])
    subtotal = models.PositiveIntegerField('Subtotal')

    class Meta:
        verbose_name = 'Línea de orden'
        verbose_name_plural = 'Líneas de orden'
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity} x {self.product_name} ({self.size}/{self.color})'

    @property
    def unit_price_formatted(self) -> str:
        return format_clp(self.unit_price)

    @property
    def subtotal_formatted(self) -> str:
        return format_clp(self.subtotal)
