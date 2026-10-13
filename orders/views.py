"""Vistas de checkout y consulta de órdenes."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from cart.cart import Cart

from .access import has_signed_access
from .forms import CheckoutForm
from .models import Order
from .regions import REGIONS, communes_for
from .services import (
    InsufficientStockError,
    OrderError,
    create_order_from_cart,
    maybe_release_expired_orders,
)

logger = logging.getLogger('orders')

#: Clave de sesión con los números de orden creados como invitado.
GUEST_ORDERS_SESSION_KEY = 'guest_orders'


def remember_guest_order(session, order: Order) -> None:
    """Permite a un invitado volver a ver su orden durante la sesión."""
    numbers = session.get(GUEST_ORDERS_SESSION_KEY, [])
    if order.order_number not in numbers:
        # Se acota la lista para no hacer crecer la sesión sin límite.
        session[GUEST_ORDERS_SESSION_KEY] = ([order.order_number] + numbers)[:20]
        session.modified = True


def _initial_from_user(user) -> dict:
    """Precarga el formulario con los datos guardados del usuario."""
    if not user.is_authenticated:
        return {}

    initial = {
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
    }
    profile = getattr(user, 'profile', None)
    if profile:
        initial.update({
            'phone': profile.phone,
            'region': profile.region,
            'commune': profile.commune,
            'address': profile.address,
            'address_number': profile.address_number,
        })
    return {k: v for k, v in initial.items() if v}


def checkout(request):
    """Formulario de checkout y creación de la orden."""
    cart = Cart(request)

    if cart.is_empty:
        messages.info(request, 'Tu carrito está vacío. Agrega productos antes de pagar.')
        return redirect('store:product_list')

    issues = cart.stock_issues()
    if issues and request.method == 'POST':
        for issue in issues:
            messages.error(request, issue)
        return redirect('cart:detail')

    if request.method == 'POST':
        maybe_release_expired_orders()
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = create_order_from_cart(
                    cart=cart,
                    data=form.cleaned_data,
                    user=request.user,
                )
            except InsufficientStockError as exc:
                for issue in exc.issues:
                    messages.error(request, issue)
                return redirect('cart:detail')
            except OrderError as exc:
                messages.error(request, str(exc))
                return redirect('cart:detail')

            if not request.user.is_authenticated:
                remember_guest_order(request.session, order)

            # El carrito se vacía solo después de que la orden existe.
            cart.clear()
            return redirect('payments:start', order_number=order.order_number)

        messages.error(request, 'Revisa los datos marcados en rojo.')
    else:
        form = CheckoutForm(initial=_initial_from_user(request.user))

    return render(request, 'orders/checkout.html', {
        'form': form,
        'cart': cart,
        'stock_issues': issues,
        'regions_json': dict(REGIONS),
        'page_title': 'Checkout',
        'meta_description': 'Finaliza tu compra de forma segura.',
        'noindex': True,
    })


def order_detail(request, order_number):
    """Detalle de una orden.

    Un usuario registrado solo puede ver sus propias órdenes. Las de invitado
    se validan contra los números guardados en su sesión.
    """
    order = get_object_or_404(
        Order.objects.prefetch_related('items').select_related('user'),
        order_number=order_number,
    )

    if not _can_access(request, order):
        # El enlace del correo de confirmación lleva una firma que autoriza
        # el acceso aunque se abra en otro dispositivo.
        if not has_signed_access(request.GET.get('acceso', ''), order):
            # 404 y no 403, para no confirmar que la orden existe.
            raise Http404('Orden no encontrada.')
        if not request.user.is_authenticated:
            remember_guest_order(request.session, order)

    return render(request, 'orders/detail.html', {
        'order': order,
        'payment': order.payments.order_by('-created_at').first(),
        'page_title': f'Orden {order.order_number}',
        'noindex': True,
    })


def _can_access(request, order: Order) -> bool:
    """Autorización de lectura de una orden concreta."""
    user = request.user
    if user.is_authenticated:
        if user.is_staff or order.user_id == user.pk:
            return True
        # Un usuario autenticado puede haber comprado antes como invitado.
        if order.user_id is None:
            return order.order_number in request.session.get(GUEST_ORDERS_SESSION_KEY, [])
        return False

    if order.user_id is not None:
        return False
    return order.order_number in request.session.get(GUEST_ORDERS_SESSION_KEY, [])


@login_required
def order_list(request):
    """Historial de órdenes del usuario autenticado."""
    orders = (
        Order.objects
        .filter(user=request.user)
        .prefetch_related('items')
        .order_by('-created_at')
    )
    page_obj = Paginator(orders, 10).get_page(request.GET.get('pagina'))

    return render(request, 'orders/list.html', {
        'page_obj': page_obj,
        'orders': page_obj.object_list,
        'page_title': 'Mis pedidos',
        'noindex': True,
    })


@require_GET
def communes_api(request):
    """Comunas de una región, para poblar el selector del checkout."""
    region = (request.GET.get('region') or '').strip()
    return JsonResponse({'communes': communes_for(region)})
