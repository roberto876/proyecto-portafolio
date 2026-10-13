"""Orquestación del flujo de pago.

Garantías que ofrece este módulo:

* El estado del pago se determina **solo** con la respuesta de Transbank.
  Nada de lo que llegue por el navegador puede marcar una orden como pagada.
* Confirmar dos veces el mismo token no descuenta stock dos veces ni crea
  pagos duplicados (idempotencia).
* Antes de aceptar un pago se verifica que el monto y la orden de compra
  devueltos por Transbank coincidan con los registrados en la base de datos.
"""
import logging
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderStatus
from orders.services import (
    InsufficientStockError,
    mark_as_cancelled,
    mark_as_paid,
    mark_as_rejected,
    reserve_stock,
)

from .models import PaymentStatus, PaymentTransaction
from .transbank import (
    MAX_SESSION_ID_LENGTH,
    CreatedTransaction,
    PaymentGatewayError,
    TransactionResult,
    get_gateway,
)

logger = logging.getLogger('payments')


class PaymentError(Exception):
    """Error de negocio del flujo de pago, con mensaje apto para el usuario."""


def build_return_url(request) -> str:
    """URL absoluta a la que Transbank devuelve al comprador."""
    return request.build_absolute_uri(reverse('payments:return'))


def build_session_id(order: Order) -> str:
    """Identificador de sesión de la transacción.

    No se usa el identificador de sesión de Django: viajaría hasta un tercero.
    """
    return f'{order.order_number}-{secrets.token_hex(4)}'[:MAX_SESSION_ID_LENGTH]


@transaction.atomic
def start_transaction(order: Order, *, return_url: str, gateway=None) -> CreatedTransaction:
    """Crea la transacción en Transbank y la registra localmente.

    :raises PaymentError: si la orden no admite pago o la pasarela falla.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.is_paid:
        raise PaymentError('Esta orden ya fue pagada.')
    if not locked.can_retry_payment:
        raise PaymentError('Esta orden ya no admite pagos.')

    # Al reintentar un pago rechazado la reserva ya se liberó: hay que volver
    # a tomarla, comprobando que las unidades sigan disponibles.
    if not locked.stock_reserved:
        try:
            reserve_stock(locked)
        except InsufficientStockError as exc:
            raise PaymentError(
                'Algunos productos de tu pedido se agotaron mientras tanto. '
                + ' '.join(exc.issues)
            ) from exc
        locked.refresh_from_db()

    gateway = gateway or get_gateway()
    session_id = build_session_id(locked)

    try:
        created = gateway.create(
            buy_order=locked.order_number,
            session_id=session_id,
            amount=locked.total,
            return_url=return_url,
        )
    except PaymentGatewayError as exc:
        logger.error('No se pudo iniciar el pago de %s: %s', locked.order_number, exc)
        raise PaymentError(str(exc)) from exc

    PaymentTransaction.objects.create(
        order=locked,
        token=created.token,
        buy_order=locked.order_number,
        session_id=session_id,
        amount=locked.total,
        status=PaymentStatus.CREATED,
    )

    # Si la orden venía de un intento rechazado, vuelve a quedar pendiente.
    if locked.status == OrderStatus.PAYMENT_REJECTED:
        locked.status = OrderStatus.PENDING_PAYMENT
        locked.save(update_fields=['status', 'updated_at'])

    logger.info('Pago iniciado para la orden %s', locked.order_number)
    return created


def _validate_against_order(result: TransactionResult, payment: PaymentTransaction) -> None:
    """Comprueba que la respuesta corresponde realmente a esta orden.

    Defensa frente a respuestas manipuladas o cruzadas entre transacciones.
    """
    if result.buy_order and result.buy_order != payment.buy_order:
        raise PaymentError('La transacción no corresponde a esta orden.')
    if result.amount and result.amount != payment.amount:
        raise PaymentError('El monto confirmado no coincide con el de la orden.')


def _apply_result(payment: PaymentTransaction, result: TransactionResult) -> None:
    """Copia el resultado de Transbank sobre la transacción local."""
    payment.status = (
        PaymentStatus.AUTHORIZED if result.is_approved else PaymentStatus.REJECTED
    )
    payment.response_code = result.response_code
    payment.authorization_code = result.authorization_code[:20]
    payment.payment_type_code = result.payment_type_code[:10]
    payment.installments_number = result.installments_number
    payment.card_last_digits = result.card_last_digits
    payment.transaction_date = result.transaction_date[:40]
    payment.raw_response = result.raw
    payment.save()


@transaction.atomic
def _claim_transaction(token: str) -> tuple[PaymentTransaction, bool]:
    """Reclama en exclusiva una transacción para confirmarla.

    Transiciona ``CREATED -> PROCESSING`` bajo bloqueo de fila y confirma la
    transacción de inmediato. Solo el proceso que gana la carrera recibe
    ``True``; cualquier callback simultáneo o repetido recibe ``False`` y no
    vuelve a llamar a Transbank.

    Es deliberado que el bloqueo se libere aquí y no se mantenga durante la
    llamada de red: retener un bloqueo de base de datos mientras se espera a
    un servicio externo agota el pool de conexiones.
    """
    payment = (
        PaymentTransaction.objects
        .select_for_update()
        .select_related('order')
        .filter(token=token)
        .first()
    )
    if payment is None:
        logger.warning('Se recibió un token desconocido en el retorno de pago')
        raise PaymentError('No encontramos la transacción indicada.')

    if payment.status != PaymentStatus.CREATED:
        logger.info(
            'Token ya procesado para la orden %s (estado=%s)',
            payment.buy_order, payment.status,
        )
        return payment, False

    payment.status = PaymentStatus.PROCESSING
    payment.save(update_fields=['status', 'updated_at'])
    return payment, True


@transaction.atomic
def _mark_payment_error(payment: PaymentTransaction, raw: dict) -> None:
    """Registra el fallo en su propia transacción.

    Debe ejecutarse fuera de la transacción que se va a revertir: si se
    guardara dentro, el rollback borraría también la traza de auditoría.
    """
    payment.status = PaymentStatus.ERROR
    payment.raw_response = raw
    payment.save(update_fields=['status', 'raw_response', 'updated_at'])


@transaction.atomic
def _settle(payment: PaymentTransaction, result: TransactionResult) -> PaymentTransaction:
    """Aplica el resultado y actualiza la orden y el inventario."""
    _apply_result(payment, result)

    if result.is_approved:
        try:
            mark_as_paid(payment.order)
        except IntegrityError:
            # La restricción única de pago autorizado por orden ya se disparó:
            # otro proceso confirmó primero. No es un error para el usuario.
            logger.warning('Confirmación concurrente para %s', payment.buy_order)
        logger.info('Pago aprobado para la orden %s', payment.buy_order)
    else:
        mark_as_rejected(payment.order)
        logger.info(
            'Pago rechazado para la orden %s (response_code=%s)',
            payment.buy_order, result.response_code,
        )

    payment.refresh_from_db()
    return payment


def confirm_transaction(token: str, *, gateway=None) -> PaymentTransaction:
    """Confirma una transacción contra Transbank. Idempotente.

    Si el token ya fue procesado, devuelve el registro existente sin volver a
    llamar a Transbank ni tocar el inventario.

    Esta función **no** es atómica en su totalidad, y eso es intencional: el
    estado de error debe sobrevivir aunque la operación falle, y la llamada de
    red ocurre sin bloqueos de base de datos abiertos.
    """
    payment, claimed = _claim_transaction(token)
    if not claimed:
        return payment

    gateway = gateway or get_gateway()

    try:
        result = gateway.commit(token)
    except PaymentGatewayError as exc:
        _mark_payment_error(payment, {'error': str(exc)})
        logger.error('Fallo al confirmar el pago de %s: %s', payment.buy_order, exc)
        raise PaymentError(str(exc)) from exc

    try:
        _validate_against_order(result, payment)
    except PaymentError:
        _mark_payment_error(payment, result.raw)
        logger.error(
            'Respuesta inconsistente para %s: buy_order=%s monto=%s',
            payment.buy_order, result.buy_order, result.amount,
        )
        raise

    return _settle(payment, result)


def _close_unfinished_payment(payment: PaymentTransaction, status: str, raw: dict) -> None:
    """Cierra un intento de pago que el comprador no terminó.

    La orden queda como «pago no completado» (reintentable) y su stock se
    libera. Nunca toca una orden pagada ni un pago que se está confirmando.
    """
    if payment.status == PaymentStatus.CREATED:
        payment.status = status
        payment.raw_response = raw
        payment.save(update_fields=['status', 'raw_response', 'updated_at'])

    if payment.status in (PaymentStatus.CANCELLED, PaymentStatus.EXPIRED):
        order = payment.order
        if not order.is_paid:
            mark_as_rejected(order)


@transaction.atomic
def cancel_transaction(*, buy_order: str, token: str) -> PaymentTransaction | None:
    """Registra la anulación hecha por el comprador en el formulario de pago.

    Corresponde al retorno con ``TBK_TOKEN``. Solo se acepta si ese token es
    exactamente el de una transacción registrada para la orden indicada: sin
    esta verificación, cualquiera podría anular órdenes ajenas enviando un
    número de orden a la URL de retorno.

    :return: la transacción, o ``None`` si los datos no son auténticos.
    """
    if not buy_order or not token:
        return None

    payment = (
        PaymentTransaction.objects
        .select_for_update()
        .select_related('order')
        .filter(buy_order=buy_order, token=token)
        .first()
    )
    if payment is None:
        logger.warning('Anulación rechazada: el token no corresponde a la orden')
        return None

    _close_unfinished_payment(
        payment, PaymentStatus.CANCELLED, {'cancelled_by_user': True},
    )
    logger.info('Pago anulado por el comprador: orden %s', buy_order)
    return payment


@transaction.atomic
def expire_transaction(*, buy_order: str, session_id: str) -> PaymentTransaction | None:
    """Registra el vencimiento del formulario de pago por inactividad.

    Corresponde al retorno con ``TBK_ORDEN_COMPRA`` y ``TBK_ID_SESION`` sin
    token. La transacción nunca llegó a confirmarse y no debe confirmarse
    ahora. Se exige que ``TBK_ID_SESION`` coincida con el ``session_id``
    aleatorio que generamos al crear la transacción, que un tercero no
    conoce.

    :return: la transacción, o ``None`` si los datos no son auténticos.
    """
    if not buy_order or not session_id:
        return None

    payment = (
        PaymentTransaction.objects
        .select_for_update()
        .select_related('order')
        .filter(buy_order=buy_order, session_id=session_id)
        .order_by('-created_at')
        .first()
    )
    if payment is None:
        logger.warning('Expiración rechazada: la sesión no corresponde a la orden')
        return None

    _close_unfinished_payment(payment, PaymentStatus.EXPIRED, {'expired': True})
    logger.info('Pago expirado por tiempo: orden %s', buy_order)
    return payment


#: Minutos tras los cuales un pago «en confirmación» se considera atascado.
STUCK_PAYMENT_MINUTES = 10


def reconcile_stuck_payments(*, gateway=None) -> int:
    """Resuelve pagos que quedaron a medio confirmar.

    Si la función se corta justo después de llamar a Transbank (por ejemplo
    por un tiempo de espera agotado), el pago queda en ``PROCESSING``. Aquí
    se consulta su estado real a Transbank, operación de solo lectura que la
    documentación oficial recomienda para estos casos, y se aplica.

    :return: número de pagos resueltos.
    """
    cutoff = timezone.now() - timedelta(minutes=STUCK_PAYMENT_MINUTES)
    stuck = list(
        PaymentTransaction.objects
        .select_related('order')
        .filter(status=PaymentStatus.PROCESSING, updated_at__lt=cutoff)[:50]
    )
    if not stuck:
        return 0

    gateway = gateway or get_gateway()
    resolved = 0
    for payment in stuck:
        try:
            result = gateway.status(payment.token)
            _validate_against_order(result, payment)
        except (PaymentGatewayError, PaymentError) as exc:
            # Se reintentará en el próximo ciclo; no se inventa un resultado.
            logger.warning('No se pudo reconciliar %s: %s', payment.buy_order, exc)
            continue
        _settle(payment, result)
        resolved += 1
        logger.info('Pago %s reconciliado (%s)', payment.buy_order, payment.status)
    return resolved
