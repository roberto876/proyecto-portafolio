"""Contexto global de la tienda disponible en todos los templates."""
from django.conf import settings
from django.urls import reverse

from .models import Category, StoreSettings


def store_context(request):
    """Ajustes de la tienda, navegación y rutas que consume el frontend.

    Las URLs se entregan al JavaScript mediante ``json_script`` en base.html,
    porque la Content-Security-Policy del sitio no permite scripts en línea.
    """
    store = StoreSettings.for_request(request)
    return {
        'store': store,
        # El queryset es perezoso: solo consulta si el template lo recorre.
        'nav_categories': Category.objects.active()[:10],
        'site_name': store.store_name,
        'free_shipping_threshold': store.free_shipping_threshold,
        'shipping_cost': store.shipping_cost,
        # Mientras Transbank esté en integración los pagos son simulados: se
        # avisa en la tienda para que nadie crea que compró de verdad.
        'payments_demo_mode': settings.TRANSBANK_ENVIRONMENT != 'production',
        'js_urls': {
            'cartAdd': reverse('cart:add'),
            'cartUpdate': reverse('cart:update'),
            'cartRemove': reverse('cart:remove'),
            'cartState': reverse('cart:state'),
            'cartDetail': reverse('cart:detail'),
            'productList': reverse('store:product_list'),
            'searchSuggestions': reverse('store:search_suggestions'),
            'communes': reverse('orders:communes_api'),
        },
    }
