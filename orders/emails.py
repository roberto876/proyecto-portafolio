"""Correos transaccionales de la tienda.

* Al cliente: confirmación de compra con el detalle y un enlace a su orden.
* A la tienda: aviso de nueva venta, al email configurado en los ajustes.

Un fallo de correo **nunca** debe afectar al pago ni a la orden: todo error se
registra en el log y se sigue adelante. Sin servidor SMTP configurado, en
desarrollo los correos se imprimen en la consola.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode

from store.models import StoreSettings

from .access import sign_order_access
from .models import Order

logger = logging.getLogger('orders')


def _order_link(order: Order) -> str:
    """Enlace absoluto a la orden que funciona desde cualquier dispositivo.

    El cliente puede abrir el correo en otro navegador, sin la sesión de la
    compra, así que el enlace lleva una firma que autoriza el acceso.
    """
    path = reverse('payments:success', args=[order.order_number])
    query = urlencode({'acceso': sign_order_access(order)})
    return f'{settings.SITE_URL.rstrip("/")}{path}?{query}'


def _send(*, subject: str, to: list[str], template: str, context: dict,
          reply_to: list[str] | None = None) -> bool:
    """Envía un correo en texto y HTML. Devuelve si se entregó al backend."""
    recipients = [address for address in to if address]
    if not recipients:
        return False
    try:
        text_body = render_to_string(f'emails/{template}.txt', context)
        html_body = render_to_string(f'emails/{template}.html', context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=[address for address in (reply_to or []) if address] or None,
        )
        message.attach_alternative(html_body, 'text/html')
        message.send()
    except Exception:  # noqa: BLE001 - el correo nunca debe romper la venta.
        logger.exception('No se pudo enviar el correo «%s»', template)
        return False
    return True


def send_order_paid_emails(order_id: int) -> None:
    """Confirma la compra al cliente y avisa a la tienda de la nueva venta."""
    try:
        order = Order.objects.prefetch_related('items').get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning('Correo de compra: la orden %s no existe', order_id)
        return

    store = StoreSettings.load()
    context = {
        'order': order,
        'store': store,
        'order_link': _order_link(order),
        'admin_link': (
            f'{settings.SITE_URL.rstrip("/")}'
            f'{reverse("admin:orders_order_change", args=[order.pk])}'
        ),
    }

    _send(
        subject=f'Tu compra en {store.store_name} está confirmada ({order.order_number})',
        to=[order.customer_email],
        template='order_confirmation',
        context=context,
        reply_to=[store.contact_email],
    )
    _send(
        subject=f'Nueva venta {order.order_number} por {order.total_formatted}',
        to=[store.contact_email],
        template='new_order_notification',
        context=context,
        reply_to=[order.customer_email],
    )
