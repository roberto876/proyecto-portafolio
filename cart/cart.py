"""Carrito de compras basado en sesión.

Reglas invariables:

* La sesión guarda únicamente ``{id_de_variante: cantidad}``.
* Los precios, nombres y stock se leen SIEMPRE desde la base de datos.
  Nada de lo que envía el navegador influye en el importe cobrado.
"""
from dataclasses import dataclass

from django.conf import settings

from store.models import ProductVariant, StoreSettings, format_clp


class CartError(Exception):
    """Error de negocio del carrito, con mensaje apto para el usuario."""


@dataclass(frozen=True)
class CartItem:
    """Línea del carrito ya resuelta contra la base de datos."""

    variant: ProductVariant
    quantity: int
    unit_price: int

    @property
    def product(self):
        return self.variant.product

    @property
    def subtotal(self) -> int:
        return self.unit_price * self.quantity

    @property
    def unit_price_formatted(self) -> str:
        return format_clp(self.unit_price)

    @property
    def subtotal_formatted(self) -> str:
        return format_clp(self.subtotal)

    @property
    def has_enough_stock(self) -> bool:
        return self.variant.available_stock >= self.quantity

    @property
    def max_quantity(self) -> int:
        """Cantidad máxima seleccionable para esta línea."""
        return min(self.variant.available_stock, settings.CART_MAX_QUANTITY_PER_ITEM)


class Cart:
    """Fachada del carrito almacenado en la sesión."""

    def __init__(self, request):
        self._request = request
        self.session = request.session
        raw = self.session.get(settings.CART_SESSION_KEY)
        if not isinstance(raw, dict):
            raw = {}
            self.session[settings.CART_SESSION_KEY] = raw
        self._data: dict[str, int] = raw
        self._items: list[CartItem] | None = None

    # -- Persistencia -------------------------------------------------------
    def save(self):
        self.session[settings.CART_SESSION_KEY] = self._data
        self.session.modified = True
        self._items = None  # Invalida la caché de líneas resueltas.

    # -- Validación ---------------------------------------------------------
    @staticmethod
    def _clean_quantity(quantity) -> int:
        """Valida la cantidad recibida desde el cliente.

        No se usa ``int()`` directamente porque acepta formas que el navegador
        nunca debería enviar: ``int('1_0')`` devuelve 10 (separador de miles
        de Python). Solo se admite una cifra escrita con dígitos.
        """
        text = str(quantity).strip()
        if text.startswith('-') and text[1:].isdecimal():
            raise CartError('La cantidad debe ser al menos 1.')
        if not text.isdecimal():
            raise CartError('La cantidad no es un número válido.')

        quantity = int(text)
        if quantity < 1:
            raise CartError('La cantidad debe ser al menos 1.')
        if quantity > settings.CART_MAX_QUANTITY_PER_ITEM:
            raise CartError(
                f'Máximo {settings.CART_MAX_QUANTITY_PER_ITEM} unidades por producto.'
            )
        return quantity

    @staticmethod
    def get_variant(variant_id) -> ProductVariant:
        """Obtiene una variante vendible o lanza ``CartError``."""
        try:
            variant_id = int(variant_id)
        except (TypeError, ValueError):
            raise CartError('Producto no válido.')

        variant = (
            ProductVariant.objects
            .select_related('product', 'product__category')
            .filter(pk=variant_id, is_active=True, product__is_active=True)
            .first()
        )
        if variant is None:
            raise CartError('El producto seleccionado ya no está disponible.')
        return variant

    # -- Operaciones --------------------------------------------------------
    def add(self, variant_id, quantity=1, *, override=False) -> CartItem:
        """Agrega una variante o ajusta su cantidad.

        Con ``override=True`` la cantidad reemplaza a la existente; si no, se
        suma a la que ya hubiera en el carrito.
        """
        variant = self.get_variant(variant_id)
        quantity = self._clean_quantity(quantity)
        key = str(variant.pk)

        if not override:
            existing = self._data.get(key, 0)
            if existing >= settings.CART_MAX_QUANTITY_PER_ITEM:
                # Evita responder «agregado» cuando en realidad no cabe más.
                raise CartError(
                    f'Ya tienes el máximo de {settings.CART_MAX_QUANTITY_PER_ITEM} '
                    f'unidades de {variant.product.name}.'
                )
            quantity = min(existing + quantity, settings.CART_MAX_QUANTITY_PER_ITEM)

        if key not in self._data and len(self._data) >= settings.CART_MAX_DISTINCT_ITEMS:
            raise CartError(
                f'El carrito admite hasta {settings.CART_MAX_DISTINCT_ITEMS} '
                'productos distintos.'
            )

        available = variant.available_stock
        if available <= 0:
            raise CartError(f'{variant.product.name} ({variant.label}) está agotado.')
        if quantity > available:
            raise CartError(
                f'Solo quedan {available} unidades de {variant.product.name} '
                f'({variant.label}).'
            )

        self._data[key] = quantity
        self.save()
        return CartItem(variant=variant, quantity=quantity, unit_price=variant.product.price)

    def update(self, variant_id, quantity) -> CartItem:
        """Fija la cantidad exacta de una línea existente."""
        key = str(variant_id).strip()
        if not key.isdigit() or key not in self._data:
            raise CartError('Ese producto no está en tu carrito.')
        return self.add(variant_id, quantity, override=True)

    def remove(self, variant_id) -> bool:
        """Elimina una línea. Devuelve ``True`` si existía."""
        key = str(variant_id)
        if key in self._data:
            del self._data[key]
            self.save()
            return True
        return False

    def clear(self):
        self._data = {}
        self.session[settings.CART_SESSION_KEY] = self._data
        self.session.modified = True
        self._items = None

    # -- Lectura ------------------------------------------------------------
    @property
    def items(self) -> list[CartItem]:
        """Líneas del carrito resueltas contra la base de datos.

        Las variantes que dejaron de existir o de estar activas se eliminan
        del carrito de forma silenciosa.
        """
        if self._items is not None:
            return self._items

        if not self._data:
            self._items = []
            return self._items

        ids = [int(k) for k in self._data if k.isdigit()]
        variants = {
            v.pk: v
            for v in ProductVariant.objects
            .select_related('product', 'product__category')
            .filter(pk__in=ids, is_active=True, product__is_active=True)
        }

        items: list[CartItem] = []
        stale = False
        for key in list(self._data):
            variant = variants.get(int(key)) if key.isdigit() else None
            if variant is None:
                del self._data[key]
                stale = True
                continue
            items.append(CartItem(
                variant=variant,
                quantity=self._data[key],
                # El precio viene del producto en base de datos, nunca del cliente.
                unit_price=variant.product.price,
            ))

        if stale:
            self.session[settings.CART_SESSION_KEY] = self._data
            self.session.modified = True

        self._items = items
        return items

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        """Número total de unidades en el carrito."""
        return sum(item.quantity for item in self.items)

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def distinct_count(self) -> int:
        return len(self.items)

    # -- Importes -----------------------------------------------------------
    @property
    def subtotal(self) -> int:
        return sum(item.subtotal for item in self.items)

    @property
    def store(self) -> StoreSettings:
        """Ajustes de la tienda (costos de despacho), una consulta por petición."""
        return StoreSettings.for_request(self._request)

    @property
    def free_shipping_available(self) -> bool:
        """Si la tienda ofrece envío gratis desde cierto monto."""
        return self.store.free_shipping_enabled

    @property
    def shipping_cost(self) -> int:
        """Costo de despacho según los ajustes editables de la tienda."""
        if self.is_empty:
            return 0
        threshold = self.store.free_shipping_threshold
        if threshold and self.subtotal >= threshold:
            return 0
        return self.store.shipping_cost

    @property
    def has_free_shipping(self) -> bool:
        return not self.is_empty and self.shipping_cost == 0

    @property
    def amount_for_free_shipping(self) -> int:
        """Cuánto falta para alcanzar el envío gratis (0 si no aplica)."""
        threshold = self.store.free_shipping_threshold
        if not threshold:
            return 0
        return max(threshold - self.subtotal, 0)

    @property
    def total(self) -> int:
        return self.subtotal + self.shipping_cost

    # -- Stock --------------------------------------------------------------
    def stock_issues(self) -> list[str]:
        """Mensajes de los problemas de stock detectados, si los hay."""
        issues = []
        for item in self.items:
            available = item.variant.available_stock
            if available == 0:
                issues.append(
                    f'{item.product.name} ({item.variant.label}) se agotó.'
                )
            elif available < item.quantity:
                issues.append(
                    f'{item.product.name} ({item.variant.label}): solo quedan '
                    f'{available} unidades (tienes {item.quantity}).'
                )
        return issues

    @property
    def is_purchasable(self) -> bool:
        return not self.is_empty and not self.stock_issues()

    # -- Serialización para el frontend -------------------------------------
    def to_dict(self) -> dict:
        """Representación JSON del carrito para las respuestas AJAX."""
        return {
            'count': len(self),
            'distinct_count': self.distinct_count,
            'subtotal': self.subtotal,
            'subtotal_formatted': format_clp(self.subtotal),
            'shipping_cost': self.shipping_cost,
            'shipping_formatted': (
                'Gratis' if self.has_free_shipping else format_clp(self.shipping_cost)
            ),
            'total': self.total,
            'total_formatted': format_clp(self.total),
            'has_free_shipping': self.has_free_shipping,
            'amount_for_free_shipping': self.amount_for_free_shipping,
            'items': [
                {
                    'variant_id': item.variant.pk,
                    'name': item.product.name,
                    'url': item.product.get_absolute_url(),
                    'image': item.product.main_image,
                    'size': item.variant.get_size_display(),
                    'color': item.variant.color,
                    'color_hex': item.variant.color_hex,
                    'quantity': item.quantity,
                    'max_quantity': item.max_quantity,
                    'unit_price': item.unit_price,
                    'unit_price_formatted': item.unit_price_formatted,
                    'subtotal': item.subtotal,
                    'subtotal_formatted': item.subtotal_formatted,
                    'in_stock': item.has_enough_stock,
                }
                for item in self.items
            ],
        }
