"""Integración con Transbank Webpay Plus (API REST v1.2).

Esta capa aísla el SDK oficial del resto de la aplicación. Cambiar entre el
ambiente de integración y el de producción es solo cambiar variables de
entorno: ninguna lógica de negocio depende del ambiente.

Referencias oficiales
---------------------
* SDK: https://github.com/TransbankDevelopers/transbank-sdk-python
* Docs: https://www.transbankdevelopers.cl/documentacion/webpay-plus

Reglas de seguridad aplicadas aquí:

* Las credenciales solo se leen de la configuración, nunca del cliente.
* Nunca se registra la API key ni datos de tarjeta en los logs.
* Una transacción se considera aprobada únicamente si Transbank responde
  ``response_code == 0`` **y** ``status == 'AUTHORIZED'``.
"""
import logging
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from transbank.common.integration_type import IntegrationType
from transbank.common.options import WebpayOptions
from transbank.error.transbank_error import TransbankError
from transbank.webpay.webpay_plus.transaction import Transaction

logger = logging.getLogger('payments')

#: Límites que impone la API de Transbank a los campos de entrada.
MAX_BUY_ORDER_LENGTH = 26
MAX_SESSION_ID_LENGTH = 61
MAX_RETURN_URL_LENGTH = 255

#: Estado que devuelve Transbank cuando la transacción fue autorizada.
STATUS_AUTHORIZED = 'AUTHORIZED'
#: Código de respuesta de una autorización exitosa.
RESPONSE_CODE_APPROVED = 0

#: Traducción de los códigos de rechazo más frecuentes a lenguaje de usuario.
RESPONSE_CODE_MESSAGES = {
    -1: 'La transacción fue rechazada por tu banco.',
    -2: 'La transacción fue rechazada. Vuelve a intentarlo.',
    -3: 'Ocurrió un error al procesar el pago.',
    -4: 'La transacción fue rechazada por tu banco.',
    -5: 'La transacción fue rechazada por posible fraude.',
    -6: 'Se alcanzó el límite de reintentos de pago.',
    -7: 'La transacción fue rechazada.',
    -8: 'La transacción fue rechazada por un rubro no autorizado.',
}
DEFAULT_REJECTION_MESSAGE = 'El pago no pudo completarse.'


class PaymentGatewayError(Exception):
    """Fallo de comunicación o de validación con la pasarela de pago."""


@dataclass(frozen=True)
class CreatedTransaction:
    """Resultado de crear una transacción: a dónde enviar al comprador."""

    token: str
    url: str

    @property
    def redirect_url(self) -> str:
        """URL completa del formulario de pago de Transbank."""
        return f'{self.url}?token_ws={self.token}'


@dataclass(frozen=True)
class TransactionResult:
    """Resultado normalizado de confirmar o consultar una transacción."""

    status: str
    response_code: int | None
    amount: int
    buy_order: str
    session_id: str
    authorization_code: str
    payment_type_code: str
    installments_number: int
    card_last_digits: str
    transaction_date: str
    raw: dict

    @property
    def is_approved(self) -> bool:
        """Una transacción solo está aprobada si Transbank lo confirma.

        Ambas condiciones son obligatorias según la documentación oficial.
        """
        return (
            self.response_code == RESPONSE_CODE_APPROVED
            and self.status == STATUS_AUTHORIZED
        )

    @property
    def user_message(self) -> str:
        """Mensaje para el comprador, sin detalles técnicos del rechazo."""
        if self.is_approved:
            return 'Pago aprobado.'
        if self.response_code is None:
            return DEFAULT_REJECTION_MESSAGE
        return RESPONSE_CODE_MESSAGES.get(self.response_code, DEFAULT_REJECTION_MESSAGE)


def _sanitize(payload: dict) -> dict:
    """Elimina cualquier dato sensible antes de persistir o registrar.

    Transbank no envía el número completo de la tarjeta (``card_number``
    contiene solo los últimos dígitos), pero se normaliza igualmente para no
    depender de esa garantía.
    """
    clean = {k: v for k, v in payload.items() if k != 'card_detail'}
    card = payload.get('card_detail') or {}
    digits = str(card.get('card_number', ''))[-4:]
    if digits:
        clean['card_last_digits'] = digits
    return clean


def _to_result(payload: dict) -> TransactionResult:
    """Convierte la respuesta cruda del SDK al resultado normalizado."""
    card = payload.get('card_detail') or {}
    try:
        response_code = int(payload['response_code'])
    except (KeyError, TypeError, ValueError):
        response_code = None

    return TransactionResult(
        status=str(payload.get('status') or ''),
        response_code=response_code,
        amount=int(payload.get('amount') or 0),
        buy_order=str(payload.get('buy_order') or ''),
        session_id=str(payload.get('session_id') or ''),
        authorization_code=str(payload.get('authorization_code') or ''),
        payment_type_code=str(payload.get('payment_type_code') or ''),
        installments_number=int(payload.get('installments_number') or 0),
        card_last_digits=str(card.get('card_number', ''))[-4:],
        transaction_date=str(payload.get('transaction_date') or ''),
        raw=_sanitize(payload),
    )


class PaymentGateway(Protocol):
    """Contrato mínimo que debe cumplir una pasarela de pago.

    Permite sustituir Transbank por un doble de prueba en los tests sin tocar
    la lógica de órdenes.
    """

    def create(self, *, buy_order: str, session_id: str, amount: int,
               return_url: str) -> CreatedTransaction: ...

    def commit(self, token: str) -> TransactionResult: ...

    def status(self, token: str) -> TransactionResult: ...


class TransbankPaymentService:
    """Implementación real sobre el SDK oficial de Transbank."""

    #: Nombre del proveedor registrado en ``PaymentTransaction``.
    PROVIDER = 'WEBPAY_PLUS'

    def __init__(self, *, commerce_code=None, api_key=None, environment=None,
                 timeout=None):
        self.environment = (environment or settings.TRANSBANK_ENVIRONMENT).lower()
        self.commerce_code = commerce_code or settings.TRANSBANK_COMMERCE_CODE
        self.api_key = api_key or settings.TRANSBANK_API_KEY
        self.timeout = timeout or settings.TRANSBANK_TIMEOUT

    @property
    def is_production(self) -> bool:
        return self.environment == 'production'

    @property
    def integration_type(self) -> IntegrationType:
        """``LIVE`` en producción, ``TEST`` en integración."""
        return IntegrationType.LIVE if self.is_production else IntegrationType.TEST

    def _transaction(self) -> Transaction:
        options = WebpayOptions(
            commerce_code=self.commerce_code,
            api_key=self.api_key,
            integration_type=self.integration_type,
            timeout=self.timeout,
        )
        return Transaction(options)

    # -- Operaciones --------------------------------------------------------
    def create(self, *, buy_order: str, session_id: str, amount: int,
               return_url: str) -> CreatedTransaction:
        """Crea la transacción y devuelve el token y la URL de pago."""
        self._validate_create_params(buy_order, session_id, amount, return_url)

        try:
            response = self._transaction().create(
                buy_order=buy_order,
                session_id=session_id,
                amount=amount,
                return_url=return_url,
            )
        except TransbankError as exc:
            logger.error(
                'Transbank rechazó la creación de la transacción %s: %s',
                buy_order, exc.message,
            )
            raise PaymentGatewayError(
                'No pudimos iniciar el pago. Inténtalo nuevamente en unos minutos.'
            ) from exc
        except Exception as exc:  # Fallos de red o del servicio remoto.
            logger.exception('Error inesperado al crear la transacción %s', buy_order)
            raise PaymentGatewayError(
                'No pudimos conectar con el medio de pago. Inténtalo nuevamente.'
            ) from exc

        token = response.get('token')
        url = response.get('url')
        if not token or not url:
            logger.error('Respuesta de creación incompleta para %s', buy_order)
            raise PaymentGatewayError('Respuesta inválida del medio de pago.')

        logger.info('Transacción Webpay creada para %s', buy_order)
        return CreatedTransaction(token=token, url=url)

    def commit(self, token: str) -> TransactionResult:
        """Confirma la transacción. Es el único origen válido del estado."""
        try:
            response = self._transaction().commit(token=token)
        except TransbankError as exc:
            logger.error('Error al confirmar la transacción: %s', exc.message)
            raise PaymentGatewayError(
                'No pudimos confirmar el pago con Transbank.'
            ) from exc
        except Exception as exc:
            logger.exception('Error inesperado al confirmar la transacción')
            raise PaymentGatewayError(
                'No pudimos confirmar el pago con Transbank.'
            ) from exc

        return _to_result(response)

    def status(self, token: str) -> TransactionResult:
        """Consulta el estado sin confirmar (usado en timeouts y auditoría)."""
        try:
            response = self._transaction().status(token=token)
        except TransbankError as exc:
            logger.error('Error al consultar el estado: %s', exc.message)
            raise PaymentGatewayError('No pudimos consultar el estado del pago.') from exc
        except Exception as exc:
            logger.exception('Error inesperado al consultar el estado')
            raise PaymentGatewayError('No pudimos consultar el estado del pago.') from exc

        return _to_result(response)

    # -- Validación ---------------------------------------------------------
    @staticmethod
    def _validate_create_params(buy_order, session_id, amount, return_url):
        """Comprueba los límites de la API antes de salir a la red."""
        if not buy_order or len(buy_order) > MAX_BUY_ORDER_LENGTH:
            raise PaymentGatewayError(
                f'buy_order inválido (máximo {MAX_BUY_ORDER_LENGTH} caracteres).'
            )
        if not session_id or len(session_id) > MAX_SESSION_ID_LENGTH:
            raise PaymentGatewayError(
                f'session_id inválido (máximo {MAX_SESSION_ID_LENGTH} caracteres).'
            )
        if not return_url or len(return_url) > MAX_RETURN_URL_LENGTH:
            raise PaymentGatewayError(
                f'return_url inválida (máximo {MAX_RETURN_URL_LENGTH} caracteres).'
            )
        if not isinstance(amount, int) or amount <= 0:
            raise PaymentGatewayError('El monto debe ser un entero positivo.')


def get_gateway() -> PaymentGateway:
    """Punto único de construcción de la pasarela.

    Los tests parchean esta función para inyectar un doble de prueba.
    """
    return TransbankPaymentService()
