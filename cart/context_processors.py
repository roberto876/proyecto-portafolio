"""Expone el carrito a todos los templates."""
from .cart import Cart


def cart_context(request):
    """El navbar necesita el contador del carrito en cada página.

    ``Cart`` es perezoso: no consulta la base de datos hasta que el template
    recorre sus líneas o pide un importe.
    """
    return {'cart': Cart(request)}
