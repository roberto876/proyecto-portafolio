"""Vistas del flujo de pago con Webpay Plus.

El endpoint de retorno acepta GET y POST porque Transbank usa uno u otro
según el ambiente y el escenario (ver documentación oficial de Webpay Plus).
Está exento de CSRF porque quien lo invoca es Transbank, no un formulario
propio; la seguridad no descansa en la cookie CSRF sino en que cada dato
recibido se contrasta con lo registrado en la base de datos y, en el caso de
un pago, con la API de Transbank.

Por qué el retorno no toca la sesión
------------------------------------
Cuando Transbank vuelve por POST desde su dominio, el navegador no envía la
cookie de sesión (política SameSite=Lax). Si en esa petición se escribiera en
la sesión, Django crearía una sesión nueva y reemplazaría la del cliente:
cerraría su cuenta y perdería el acceso a su orden. Por eso el retorno solo
redirige, adjuntando un enlace firmado que la página siguiente (ya con las
cookies correctas) usa para autorizar el acceso.
"""
import logging

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from orders.access import has_signed_access, sign_order_access
from orders.models import Order
from orders.views import _can_access, remember_guest_order

from .models import PaymentStatus, PaymentTransaction
from .services import (
    PaymentError,
    build_return_url,
    cancel_transaction,
    confirm_transaction,
    expire_transaction,
    start_transaction,
)

logger = logging.getLogger('payments')

# ---------------------------------------------------------------------------
# Enlaces de acceso firmados (ver orders/access.py)
# ---------------------------------------------------------------------------
__all__ = ['sign_order_access']  # Reexportado para el resto del proyecto.


def _has_signed_access(request, order: Order) -> bool:
    """Valida el parámetro ``acceso`` de la URL, si viene."""
    return has_signed_access(request.GET.get('acceso', ''), order)


def _authorize(request, order: Order) -> bool:
    """Autoriza la vista de una orden por sesión o por enlace firmado.

    Si el acceso llega por enlace firmado, la orden se recuerda en la sesión
    para que el comprador pueda volver a verla sin el enlace.
    """
    if _can_access(request, order):
        return True
    if _has_signed_access(request, order):
        if not (request.user.is_authenticated and order.user_id == request.user.pk):
            remember_guest_order(request.session, order)
        return True
    return False


def _result_redirect(payment: PaymentTransaction):
    """Lleva a la página de éxito o de fallo con un enlace de acceso firmado."""
    order = payment.order
    name = 'payments:success' if payment.is_approved else 'payments:failure'
    url = reverse(name, args=[order.order_number])
    return redirect(f'{url}?{urlencode({"acceso": sign_order_access(order)})}')


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
def start_payment(request, order_number):
    """Crea la transacción y redirige al comprador al formulario de Webpay."""
    order = get_object_or_404(Order, order_number=order_number)

    if not _authorize(request, order):
        raise Http404('Orden no encontrada.')

    if order.is_paid:
        return redirect('payments:success', order_number=order.order_number)

    try:
        created = start_transaction(order, return_url=build_return_url(request))
    except PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('orders:detail', order_number=order.order_number)

    # Página puente: publica un formulario auto-enviado hacia Webpay, que es
    # la forma que documenta Transbank para entregar el token.
    return render(request, 'payments/redirect.html', {
        'webpay_url': created.url,
        'token': created.token,
        'order': order,
        'page_title': 'Redirigiendo a Webpay',
        'noindex': True,
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def payment_return(request):
    """Retorno desde Webpay.

    Casos documentados por Transbank:

    1. ``token_ws``                    -> flujo normal, hay que confirmar.
    2. ``TBK_TOKEN`` + orden + sesión  -> el comprador anuló el pago.
    3. orden + sesión, sin token       -> el formulario expiró por tiempo.
    4. ``token_ws`` + ``TBK_TOKEN``    -> error en el formulario de pago.

    En los casos 2 a 4 los datos llegan desde el navegador, así que solo se
    actúa si coinciden con una transacción registrada por nosotros.
    """
    data = request.POST if request.method == 'POST' else request.GET
    token_ws = (data.get('token_ws') or '').strip()
    tbk_token = (data.get('TBK_TOKEN') or '').strip()
    buy_order = (data.get('TBK_ORDEN_COMPRA') or '').strip()
    session_id = (data.get('TBK_ID_SESION') or '').strip()

    # Casos 2 y 4: anulación o error en el formulario. Nunca se confirma.
    if tbk_token:
        payment = (
            cancel_transaction(buy_order=buy_order, token=tbk_token)
            or (token_ws and cancel_transaction(buy_order=buy_order, token=token_ws))
        )
        if not payment:
            return _unrecognized_return()
        messages.warning(request, 'El pago no se completó. Puedes intentarlo de nuevo.')
        return _result_redirect(payment)

    # Caso 3: el formulario de pago expiró por inactividad.
    if not token_ws:
        payment = expire_transaction(buy_order=buy_order, session_id=session_id)
        if not payment:
            return _unrecognized_return()
        messages.warning(request, 'El tiempo para pagar expiró. Puedes intentarlo de nuevo.')
        return _result_redirect(payment)

    # Caso 1: flujo normal. El estado lo decide Transbank, no el navegador.
    try:
        payment = confirm_transaction(token_ws)
    except PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('store:home')

    return _result_redirect(payment)


def _unrecognized_return():
    """Respuesta ante un retorno que no corresponde a ninguna transacción.

    Deliberadamente genérica: no confirma si la orden existe.
    """
    logger.warning('Retorno de pago con datos no reconocidos')
    return redirect('store:home')


def payment_success(request, order_number):
    """Confirmación de compra exitosa."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items'), order_number=order_number,
    )
    if not _authorize(request, order):
        raise Http404('Orden no encontrada.')

    if not order.is_paid:
        return redirect('payments:failure', order_number=order.order_number)

    payment = order.payments.filter(status=PaymentStatus.AUTHORIZED).first()
    return render(request, 'payments/success.html', {
        'order': order,
        'payment': payment,
        'page_title': f'Compra confirmada · Orden {order.order_number}',
        'noindex': True,
    })


def payment_failure(request, order_number):
    """Pago rechazado, anulado o expirado."""
    order = get_object_or_404(Order, order_number=order_number)
    if not _authorize(request, order):
        raise Http404('Orden no encontrada.')

    if order.is_paid:
        return redirect('payments:success', order_number=order.order_number)

    payment = order.payments.order_by('-created_at').first()
    return render(request, 'payments/failure.html', {
        'order': order,
        'payment': payment,
        # Mensaje genérico: no se exponen detalles técnicos del rechazo.
        'reason': _failure_reason(payment),
        'page_title': f'Pago no completado · Orden {order.order_number}',
        'noindex': True,
    })


def _failure_reason(payment: PaymentTransaction | None) -> str:
    """Explicación en lenguaje llano de por qué no se completó el pago."""
    if payment is None:
        return 'No se registró ningún intento de pago para esta orden.'
    return {
        PaymentStatus.CANCELLED: 'Anulaste el pago antes de completarlo.',
        PaymentStatus.EXPIRED: 'El tiempo disponible para pagar expiró.',
        PaymentStatus.ERROR: 'Hubo un problema de comunicación con el medio de pago.',
        PaymentStatus.PROCESSING: (
            'Estamos confirmando tu pago con el banco. Si el cargo se realizó, '
            'tu pedido se actualizará en unos minutos.'
        ),
        PaymentStatus.REJECTED: (
            'Tu banco rechazó la transacción. Revisa el cupo disponible o '
            'prueba con otro medio de pago.'
        ),
    }.get(payment.status, 'El pago no pudo completarse.')
