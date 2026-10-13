"""Vistas del catálogo y páginas institucionales."""
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from orders.services import maybe_release_expired_orders

from .forms import ContactForm
from .models import Category, Product, ProductVariant, Size, StoreSettings
from .services import (
    SORT_LABELS,
    build_querystring,
    filter_products,
    parse_filters,
)

SITE = settings.SITE_NAME

#: Orden de exhibición de tallas en la ficha de producto.
SIZE_DISPLAY_ORDER = Size.values


def _paginate(request, queryset):
    """Pagina un queryset usando el parámetro `pagina`."""
    paginator = Paginator(queryset, settings.PRODUCTS_PER_PAGE)
    return paginator.get_page(request.GET.get('pagina'))


def home(request):
    """Portada: categorías, destacados y novedades."""
    categories = Category.objects.active()[:8]
    featured = (
        Product.objects.active().with_catalog_data()
        .filter(is_featured=True).order_by('-created_at')[:8]
    )
    latest = (
        Product.objects.active().with_catalog_data()
        .order_by('-created_at')[:8]
    )
    on_sale = (
        Product.objects.active().with_catalog_data()
        .on_sale().order_by('-created_at')[:4]
    )

    return render(request, 'home.html', {
        'categories': categories,
        'featured_products': featured,
        'latest_products': latest,
        'sale_products': on_sale,
        'meta_description': (
            'Ropa deportiva de alto rendimiento: poleras, shorts, calzas, '
            'polerones, tops y conjuntos. Envíos a todo Chile y pago seguro '
            'con Webpay.'
        ),
    })


def _render_catalog(request, *, on_sale=False, template='store/product_list.html'):
    """Cuerpo compartido por el catálogo y la vista de ofertas."""
    filters = parse_filters(request.GET, on_sale=on_sale)
    page_obj = _paginate(request, filter_products(filters))

    # Opciones de filtro derivadas del stock realmente vendible.
    purchasable = ProductVariant.objects.purchasable()
    sizes = list(
        purchasable.values_list('size', flat=True).distinct()
    )
    colors = list(
        purchasable.values('color', 'color_hex').distinct().order_by('color')
    )

    title = 'Ofertas' if on_sale else 'Catálogo'
    return render(request, template, {
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'filters': filters,
        'sort_labels': SORT_LABELS,
        'all_categories': Category.objects.active(),
        'all_sizes': sizes,
        'all_colors': colors,
        'is_offers_view': on_sale,
        'base_querystring': build_querystring(request.GET, pagina=None),
        'page_title': title,
        'meta_description': (
            'Aprovecha los descuentos vigentes en ropa deportiva.'
            if on_sale else
            'Explora la colección completa. Filtra por categoría, género, '
            'talla, color y precio.'
        ),
    })


def product_list(request):
    """Catálogo con filtros, orden, búsqueda y paginación."""
    return _render_catalog(request)


def offers(request):
    """Listado de productos con precio rebajado."""
    return _render_catalog(request, on_sale=True)


def product_detail(request, slug):
    """Ficha de producto con galería, variantes y relacionados."""
    # El stock mostrado debe reflejar las reservas ya vencidas.
    maybe_release_expired_orders()
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('images', 'variants'),
        slug=slug,
        is_active=True,
    )
    variants = product.active_variants

    # Matriz talla/color que consume product.js para habilitar o deshabilitar
    # combinaciones sin stock. Solo expone datos públicos.
    variant_matrix = {
        f'{variant.size}|{variant.color}': {
            'id': variant.id,
            'size': variant.size,
            'color': variant.color,
            'color_hex': variant.color_hex,
            'stock': variant.available_stock,
        }
        for variant in variants
    }

    # Tallas y colores que existen para el producto, en orden estable. Las
    # combinaciones sin stock se muestran deshabilitadas, no ocultas.
    present_sizes = {v.size for v in variants}
    all_sizes = [s for s in SIZE_DISPLAY_ORDER if s in present_sizes]
    all_colors = list(dict.fromkeys((v.color, v.color_hex) for v in variants))

    related = (
        Product.objects.active().with_catalog_data()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .order_by('-is_featured', '-sales_count')[:4]
    )

    description = product.description.strip().replace('\n', ' ')
    return render(request, 'store/product_detail.html', {
        'product': product,
        'variants': variants,
        'variant_matrix': variant_matrix,
        'sizes': all_sizes,
        'colors': [{'color': c, 'color_hex': h} for c, h in all_colors],
        'related_products': related,
        'page_title': product.name,
        'meta_description': (
            description[:157] + '…' if len(description) > 158
            else description or f'Compra {product.name} con despacho a todo Chile.'
        ),
        'og_image': product.main_image,
        'canonical_path': product.get_absolute_url(),
    })


@require_GET
def variant_stock(request, product_id: int):
    """Consulta AJAX del stock disponible de una combinación talla/color."""
    size = (request.GET.get('size') or '').strip().upper()
    color = (request.GET.get('color') or '').strip()

    variant = (
        ProductVariant.objects
        .filter(
            product_id=product_id,
            product__is_active=True,
            size=size,
            color__iexact=color,
            is_active=True,
        )
        .first()
    )
    if variant is None:
        return JsonResponse({'available': False, 'stock': 0})

    return JsonResponse({
        'available': variant.available_stock > 0,
        'stock': variant.available_stock,
        'variant_id': variant.id,
    })


@require_GET
def search_suggestions(request):
    """Sugerencias del buscador del navbar."""
    query = (request.GET.get('q') or '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    products = (
        Product.objects.active()
        .select_related('category')
        .filter(name__icontains=query[:100])[:6]
    )
    return JsonResponse({'results': [
        {
            'name': p.name,
            'price': p.price_formatted,
            'image': p.main_image,
            'url': p.get_absolute_url(),
            'category': p.category.name,
        }
        for p in products
    ]})


# ---------------------------------------------------------------------------
# Páginas institucionales
# ---------------------------------------------------------------------------
def about(request):
    return render(request, 'pages/about.html', {
        'page_title': 'Sobre nosotros',
        'meta_description': (
            'Ropa deportiva pensada para entrenar fuerte y durar. '
            'Conoce nuestra historia.'
        ),
    })


def contact(request):
    """Formulario de contacto con protección CSRF y honeypot antispam."""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            store = StoreSettings.for_request(request)
            form.send(recipient=store.contact_email, store_name=store.store_name)
            messages.success(
                request,
                'Mensaje enviado. Te responderemos dentro de 24 horas hábiles.',
            )
            return redirect('store:contact')
        messages.error(request, 'Revisa los campos marcados e inténtalo de nuevo.')
    else:
        form = ContactForm()

    return render(request, 'pages/contact.html', {
        'form': form,
        'page_title': 'Contacto',
        'meta_description': 'Escríbenos: respondemos en menos de 24 horas hábiles.',
    })


def legal_page(request, template, title):
    return render(request, template, {
        'page_title': title,
        'meta_description': f'{title} de la tienda.',
    })


def terms(request):
    return legal_page(request, 'pages/terms.html', 'Términos y condiciones')


def privacy(request):
    return legal_page(request, 'pages/privacy.html', 'Política de privacidad')


def shipping(request):
    return legal_page(request, 'pages/shipping.html', 'Envíos y devoluciones')


# ---------------------------------------------------------------------------
# Manejadores de error
# ---------------------------------------------------------------------------
def custom_400(request, exception=None):
    return render(request, 'errors/400.html', status=400)


def custom_403(request, exception=None):
    return render(request, 'errors/403.html', status=403)


def custom_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def custom_500(request):
    return render(request, 'errors/500.html', status=500)
