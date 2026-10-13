"""Modelo de transacciones de pago.

Política de datos sensibles: **nunca** se almacena el número completo de la
tarjeta, su fecha de vencimiento ni el CVV. Transbank procesa el pago en su
propia infraestructura; aquí solo se guarda el rastro necesario para
conciliar la venta (token, códigos de respuesta y los últimos 4 dígitos que
el propio Transbank devuelve).
"""
from django.db import models

from store.models import format_clp


class PaymentStatus(models.TextChoices):
    """Estado de una transacción de pago."""

    CREATED = 'CREATED', 'Creada'
    #: Reclamada por un proceso que está confirmándola contra Transbank.
    #: Evita que dos callbacks simultáneos la confirmen dos veces.
    PROCESSING = 'PROCESSING', 'En confirmación'
    AUTHORIZED = 'AUTHORIZED', 'Autorizada'
    REJECTED = 'REJECTED', 'Rechazada'
    CANCELLED = 'CANCELLED', 'Anulada por el usuario'
    EXPIRED = 'EXPIRED', 'Expirada por tiempo'
    ERROR = 'ERROR', 'Error de comunicación'


class PaymentTransaction(models.Model):
    """Intento de pago asociado a una orden.

    Una orden puede tener varias transacciones (por ejemplo si el primer
    intento fue rechazado y el cliente reintentó), pero solo una puede quedar
    en estado ``AUTHORIZED``.
    """

    order = models.ForeignKey(
        'orders.Order', on_delete=models.PROTECT,
        related_name='payments', verbose_name='Orden',
    )
    provider = models.CharField('Proveedor', max_length=30, default='WEBPAY_PLUS')

    # Identificadores de la transacción en Transbank.
    token = models.CharField(
        'Token', max_length=64, unique=True,
        help_text='token_ws devuelto por Transbank.',
    )
    buy_order = models.CharField('Orden de compra', max_length=26)
    session_id = models.CharField('ID de sesión', max_length=61, blank=True)
    amount = models.PositiveIntegerField('Monto')

    # Resultado.
    status = models.CharField(
        'Estado', max_length=20,
        choices=PaymentStatus.choices, default=PaymentStatus.CREATED,
    )
    response_code = models.IntegerField('Código de respuesta', null=True, blank=True)
    authorization_code = models.CharField(
        'Código de autorización', max_length=20, blank=True,
    )
    payment_type_code = models.CharField('Tipo de pago', max_length=10, blank=True)
    installments_number = models.PositiveIntegerField('Cuotas', default=0)
    card_last_digits = models.CharField(
        'Últimos 4 dígitos', max_length=4, blank=True,
        help_text='Único dato de la tarjeta que se conserva.',
    )
    transaction_date = models.CharField('Fecha Transbank', max_length=40, blank=True)

    # Respuesta cruda ya saneada, útil para conciliación y soporte.
    raw_response = models.JSONField('Respuesta (saneada)', default=dict, blank=True)

    created_at = models.DateTimeField('Creada', auto_now_add=True)
    updated_at = models.DateTimeField('Actualizada', auto_now=True)

    class Meta:
        verbose_name = 'Transacción de pago'
        verbose_name_plural = 'Transacciones de pago'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['buy_order']),
        ]
        constraints = [
            # Refuerzo a nivel de base de datos: una orden no puede tener dos
            # pagos autorizados, ni siquiera ante una condición de carrera.
            models.UniqueConstraint(
                fields=['order'],
                condition=models.Q(status='AUTHORIZED'),
                name='unique_authorized_payment_per_order',
            ),
        ]

    def __str__(self):
        return f'{self.buy_order} — {self.get_status_display()}'

    @property
    def is_approved(self) -> bool:
        return self.status == PaymentStatus.AUTHORIZED

    @property
    def amount_formatted(self) -> str:
        return format_clp(self.amount)

    @property
    def payment_type_display(self) -> str:
        """Traduce el código de tipo de pago de Transbank."""
        return {
            'VD': 'Débito',
            'VN': 'Crédito sin cuotas',
            'VC': 'Crédito en cuotas',
            'SI': 'Crédito, 3 cuotas sin interés',
            'S2': 'Crédito, 2 cuotas sin interés',
            'NC': 'Crédito, N cuotas sin interés',
            'VP': 'Prepago',
        }.get(self.payment_type_code, self.payment_type_code or '—')

    @property
    def masked_card(self) -> str:
        return f'•••• {self.card_last_digits}' if self.card_last_digits else '—'
