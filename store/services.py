"""Lógica de catálogo: filtrado, orden y búsqueda.

Se mantiene fuera de las vistas para poder testearla de forma aislada.
"""
from dataclasses import dataclass, field

from django.db.models import Q, QuerySet

from .models import Product, Size

#: Opciones de orden expuestas en la UI -> expresión de orden del ORM.
SORT_OPTIONS = {
    'recientes': ('-created_at',),
    'precio_asc': ('price', '-created_at'),
    'precio_desc': ('-price', '-created_at'),
    'vendidos': ('-sales_count', '-created_at'),
    'nombre': ('name',),
}
DEFAULT_SORT = 'recientes'

#: Etiquetas legibles para el selector de orden.
SORT_LABELS = {
    'recientes': 'Más recientes',
    'precio_asc': 'Precio: menor a mayor',
    'precio_desc': 'Precio: mayor a menor',
    'vendidos': 'Más vendidos',
    'nombre': 'Nombre (A-Z)',
}

#: Tope defensivo para los filtros de precio enviados por el cliente.
MAX_PRICE_FILTER = 100_000_000


def _parse_positive_int(raw: str | None) -> int | None:
    """Convierte un valor de query string a entero positivo, o ``None``."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if 0 <= value <= MAX_PRICE_FILTER else None


@dataclass
class CatalogFilters:
    """Filtros del catálogo ya normalizados y validados."""

    query: str = ''
    category: str = ''
    gender: str = ''
    size: str = ''
    color: str = ''
    price_min: int | None = None
    price_max: int | None = None
    sort: str = DEFAULT_SORT
    on_sale: bool = False
    applied: list[str] = field(default_factory=list)

    @property
    def has_filters(self) -> bool:
        return bool(
            self.query or self.category or self.gender or self.size
            or self.color or self.price_min is not None
            or self.price_max is not None
        )


def parse_filters(params, *, on_sale: bool = False) -> CatalogFilters:
    """Normaliza los parámetros GET.

    Todo valor que no supere la validación se descarta en silencio: nunca se
    confía en la entrada del navegador.
    """
    valid_sizes = set(Size.values)
    valid_genders = {'H', 'M', 'U'}

    size = (params.get('talla') or '').strip().upper()
    gender = (params.get('genero') or '').strip().upper()
    sort = (params.get('orden') or '').strip().lower()

    price_min = _parse_positive_int(params.get('precio_min'))
    price_max = _parse_positive_int(params.get('precio_max'))
    # Un rango invertido es un error del cliente: se ignora en vez de devolver
    # un listado vacío sin explicación.
    if price_min is not None and price_max is not None and price_min > price_max:
        price_min, price_max = price_max, price_min

    return CatalogFilters(
        query=(params.get('q') or '').strip()[:100],
        category=(params.get('categoria') or '').strip()[:200],
        gender=gender if gender in valid_genders else '',
        size=size if size in valid_sizes else '',
        color=(params.get('color') or '').strip()[:50],
        price_min=price_min,
        price_max=price_max,
        sort=sort if sort in SORT_OPTIONS else DEFAULT_SORT,
        on_sale=on_sale,
    )


def filter_products(filters: CatalogFilters) -> QuerySet[Product]:
    """Aplica los filtros sobre el catálogo activo."""
    products = Product.objects.active().with_catalog_data()

    if filters.on_sale:
        products = products.on_sale()

    if filters.query:
        products = products.filter(
            Q(name__icontains=filters.query)
            | Q(description__icontains=filters.query)
            | Q(sku__icontains=filters.query)
            | Q(category__name__icontains=filters.query)
        )

    if filters.category:
        products = products.filter(category__slug=filters.category)

    if filters.gender:
        products = products.filter(gender=filters.gender)

    if filters.size:
        products = products.filter(
            variants__size=filters.size,
            variants__is_active=True,
            variants__stock__gt=0,
        )

    if filters.color:
        products = products.filter(
            variants__color__iexact=filters.color,
            variants__is_active=True,
            variants__stock__gt=0,
        )

    if filters.price_min is not None:
        products = products.filter(price__gte=filters.price_min)

    if filters.price_max is not None:
        products = products.filter(price__lte=filters.price_max)

    # `distinct` es necesario porque los filtros de variante hacen JOIN.
    if filters.size or filters.color:
        products = products.distinct()

    return products.order_by(*SORT_OPTIONS[filters.sort])


def build_querystring(params, **overrides) -> str:
    """Reconstruye la query string conservando filtros y cambiando `overrides`.

    Se usa para la paginación y el selector de orden, de modo que navegar no
    pierda los filtros activos.
    """
    data = params.copy()
    for key, value in overrides.items():
        if value in (None, ''):
            data.pop(key, None)
        else:
            data[key] = value
    encoded = data.urlencode()
    return f'?{encoded}' if encoded else ''
