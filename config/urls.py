"""Rutas raíz del proyecto."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from ops.views import store_status
from store.sitemaps import CategorySitemap, ProductSitemap, StaticViewSitemap

sitemaps = {
    'static': StaticViewSitemap,
    'categories': CategorySitemap,
    'products': ProductSitemap,
}

urlpatterns = [
    # Antes de admin.site.urls para que no la capture el panel.
    path('admin/estado/', admin.site.admin_view(store_status), name='store_status'),
    path('admin/', admin.site.urls),
    path('cuenta/', include('accounts.urls')),
    path('carrito/', include('cart.urls')),
    path('pedidos/', include('orders.urls')),
    path('pagos/', include('payments.urls')),
    path('ops/', include('ops.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps},
         name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt', content_type='text/plain',
    ), name='robots'),
    # La app de tienda captura la raíz y debe ir al final.
    path('', include('store.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Manejadores de error personalizados.
handler400 = 'store.views.custom_400'
handler403 = 'store.views.custom_403'
handler404 = 'store.views.custom_404'
handler500 = 'store.views.custom_500'

# Personalización del panel de administración. Es genérica a propósito: el
# nombre de la tienda se edita en «Ajustes de la tienda».
admin.site.site_header = 'Panel de la tienda'
admin.site.site_title = 'Panel de la tienda'
admin.site.index_title = 'Inicio'
