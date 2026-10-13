"""Enlaces firmados que autorizan la consulta de una orden.

Se usan al volver de Webpay (el retorno por POST llega sin cookies) y en el
correo de confirmación (el cliente puede abrirlo en otro dispositivo). La
firma es de Django (HMAC con SECRET_KEY): no se puede falsificar ni reutilizar
para otra orden.
"""
from django.conf import settings
from django.core import signing

#: Sal criptográfica: separa estas firmas de cualquier otra del proyecto.
ACCESS_SALT = 'payments.order-access'


def sign_order_access(order) -> str:
    """Firma el número de orden."""
    return signing.dumps(order.order_number, salt=ACCESS_SALT)


def has_signed_access(token: str, order) -> bool:
    """Indica si ``token`` es una firma válida y vigente para esta orden."""
    if not token:
        return False
    try:
        value = signing.loads(
            token, salt=ACCESS_SALT, max_age=settings.PAYMENT_ACCESS_MAX_AGE,
        )
    except signing.BadSignature:
        return False
    return value == order.order_number
