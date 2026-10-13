"""Vistas del carrito.

Todas las mutaciones son POST y pasan por la protección CSRF de Django. Los
endpoints AJAX devuelven el estado completo del carrito recalculado en el
servidor, de modo que el frontend nunca decide importes.
"""
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from orders.services import maybe_release_expired_orders

from .cart import Cart, CartError

logger = logging.getLogger('cart')


def _is_ajax(request) -> bool:
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _respond(request, cart, *, ok=True, message='', status=200, redirect_to='cart:detail'):
    """Responde JSON para peticiones AJAX y redirección para formularios."""
    if _is_ajax(request):
        payload = {'ok': ok, 'message': message, 'cart': cart.to_dict()}
        return JsonResponse(payload, status=status)

    if message:
        (messages.success if ok else messages.error)(request, message)
    return redirect(redirect_to)


def cart_detail(request):
    """Página del carrito."""
    cart = Cart(request)
    return render(request, 'cart/detail.html', {
        'cart': cart,
        'stock_issues': cart.stock_issues(),
        'page_title': 'Tu carrito',
        'meta_description': 'Revisa los productos de tu carrito antes de pagar.',
        'noindex': True,
    })


@require_POST
def cart_add(request):
    """Agrega una variante al carrito."""
    # Devuelve a la venta el stock de carritos abandonados antes de validar.
    maybe_release_expired_orders()
    cart = Cart(request)
    try:
        item = cart.add(
            request.POST.get('variant_id'),
            request.POST.get('quantity', 1),
            override=request.POST.get('override') == 'true',
        )
    except CartError as exc:
        return _respond(request, cart, ok=False, message=str(exc), status=400)

    return _respond(
        request, cart,
        message=f'{item.product.name} ({item.variant.label}) agregado al carrito.',
    )


@require_POST
def cart_update(request):
    """Fija la cantidad de una línea existente."""
    cart = Cart(request)
    try:
        cart.update(request.POST.get('variant_id'), request.POST.get('quantity'))
    except CartError as exc:
        return _respond(request, cart, ok=False, message=str(exc), status=400)

    return _respond(request, cart, message='Carrito actualizado.')


@require_POST
def cart_remove(request):
    """Elimina una línea del carrito."""
    cart = Cart(request)
    removed = cart.remove(request.POST.get('variant_id'))
    if not removed:
        return _respond(
            request, cart, ok=False,
            message='Ese producto no está en tu carrito.', status=400,
        )
    return _respond(request, cart, message='Producto eliminado del carrito.')


@require_POST
def cart_clear(request):
    """Vacía el carrito."""
    cart = Cart(request)
    cart.clear()
    return _respond(request, cart, message='Carrito vaciado.')


def cart_state(request):
    """Estado actual del carrito, usado por el mini-carrito del navbar."""
    return JsonResponse({'ok': True, 'cart': Cart(request).to_dict()})
