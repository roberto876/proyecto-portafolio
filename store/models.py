"""Modelos del catálogo: categorías, productos, imágenes y variantes."""
import uuid

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Gender(models.TextChoices):
    """Público objetivo de un producto."""

    HOMBRE = 'H', 'Hombre'
    MUJER = 'M', 'Mujer'
    UNISEX = 'U', 'Unisex'


class Size(models.TextChoices):
    """Tallas disponibles, ordenadas de menor a mayor."""

    XS = 'XS', 'XS'
    S = 'S', 'S'
    M = 'M', 'M'
    L = 'L', 'L'
    XL = 'XL', 'XL'
    XXL = 'XXL', 'XXL'
    UNICA = 'UNICA', 'Talla única'


#: Orden de exhibición de las tallas (las claves siguen el orden de `Size`).
SIZE_ORDER: dict[str, int] = {
    str(size): index for index, size in enumerate(Size.values)
}


def format_clp(value: int) -> str:
    """Formatea un entero como precio chileno: 24990 -> '$24.990'."""
    return f'${value:,.0f}'.replace(',', '.')


class TimeStampedModel(models.Model):
    """Mixin con marcas de tiempo de creación y actualización."""

    created_at = models.DateTimeField('Creado', auto_now_add=True)
    updated_at = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        abstract = True


class CategoryQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Category(TimeStampedModel):
    """Categoría de producto (poleras, shorts, leggings, ...)."""

    name = models.CharField('Nombre', max_length=200)
    slug = models.SlugField('Slug', max_length=200, unique=True)
    description = models.TextField('Descripción', blank=True)
    image = models.URLField('URL de imagen', max_length=500, blank=True)
    is_active = models.BooleanField('Activa', default=True)
    sort_order = models.PositiveIntegerField('Orden', default=0)

    objects = CategoryQuerySet.as_manager()

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['is_active', 'sort_order']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"{reverse('store:product_list')}?categoria={self.slug}"


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_catalog_data(self):
        """Evita el problema N+1 al listar productos."""
        return self.select_related('category').prefetch_related('variants')

    def on_sale(self):
        return self.filter(compare_price__isnull=False, compare_price__gt=models.F('price'))


class Product(TimeStampedModel):
    """Producto del catálogo. El stock vive en sus variantes."""

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Categoría',
    )
    name = models.CharField('Nombre', max_length=300)
    slug = models.SlugField('Slug', max_length=300, unique=True)
    description = models.TextField('Descripción', blank=True)
    gender = models.CharField(
        'Género', max_length=1, choices=Gender.choices, default=Gender.UNISEX,
    )
    price = models.PositiveIntegerField(
        'Precio (CLP)', validators=[MinValueValidator(1)],
    )
    compare_price = models.PositiveIntegerField(
        'Precio anterior (CLP)', null=True, blank=True,
        help_text='Déjalo vacío si el producto no está en oferta.',
    )
    sku = models.CharField('SKU', max_length=50, unique=True, blank=True)
    main_image = models.URLField('URL de imagen principal', max_length=500, blank=True)
    is_active = models.BooleanField('Activo', default=True)
    is_featured = models.BooleanField('Destacado', default=False)
    sales_count = models.PositiveIntegerField('Unidades vendidas', default=0)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['is_active', 'price']),
            models.Index(fields=['is_active', '-sales_count']),
            models.Index(fields=['gender']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(compare_price__isnull=True)
                | models.Q(compare_price__gt=models.F('price')),
                name='compare_price_gt_price',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)[:280] or 'producto'
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f'{base_slug}-{counter}'
            self.slug = slug
        if not self.sku:
            self.sku = f'GF-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('store:product_detail', kwargs={'slug': self.slug})

    # -- Precio -------------------------------------------------------------
    @property
    def is_on_sale(self) -> bool:
        compare = self.compare_price
        return compare is not None and compare > self.price

    @property
    def discount_percentage(self) -> int:
        compare = self.compare_price
        if compare is None or compare <= self.price:
            return 0
        return round((1 - self.price / compare) * 100)

    @property
    def price_formatted(self) -> str:
        return format_clp(self.price)

    @property
    def compare_price_formatted(self) -> str:
        return format_clp(self.compare_price) if self.compare_price else ''

    # -- Stock --------------------------------------------------------------
    @property
    def active_variants(self):
        """Variantes activas, aprovechando el prefetch si existe."""
        return [v for v in self.variants.all() if v.is_active]

    @property
    def total_stock(self) -> int:
        return sum(v.available_stock for v in self.active_variants)

    @property
    def in_stock(self) -> bool:
        return self.total_stock > 0

    @property
    def available_sizes(self) -> list[str]:
        sizes = {v.size for v in self.active_variants if v.available_stock > 0}
        return sorted(sizes, key=lambda s: SIZE_ORDER.get(s, 99))

    @property
    def available_colors(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for variant in self.active_variants:
            if variant.available_stock > 0 and variant.color not in seen:
                seen[variant.color] = {
                    'color': variant.color,
                    'color_hex': variant.color_hex,
                }
        return list(seen.values())

    @property
    def gallery_images(self) -> list[str]:
        """Imagen principal seguida de las adicionales, sin duplicados."""
        images = [self.main_image] if self.main_image else []
        images += [img.image for img in self.images.all()]
        return list(dict.fromkeys(images))


class ProductImage(models.Model):
    """Imagen adicional de la galería de un producto."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images',
        verbose_name='Producto',
    )
    image = models.URLField('URL de imagen', max_length=500)
    alt_text = models.CharField('Texto alternativo', max_length=200, blank=True)
    sort_order = models.PositiveIntegerField('Orden', default=0)

    class Meta:
        verbose_name = 'Imagen de producto'
        verbose_name_plural = 'Imágenes de producto'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.product.name} — imagen {self.sort_order}'


class ProductVariantQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def purchasable(self):
        """Variantes activas con al menos una unidad disponible."""
        return self.active().filter(stock__gt=models.F('reserved'))


class ProductVariant(models.Model):
    """Combinación talla/color con su propio stock.

    ``stock`` es el inventario físico y ``reserved`` la parte comprometida por
    órdenes pendientes de pago. Lo que se puede vender es la diferencia.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants',
        verbose_name='Producto',
    )
    size = models.CharField('Talla', max_length=10, choices=Size.choices)
    color = models.CharField('Color', max_length=50)
    color_hex = models.CharField(
        'Color HEX', max_length=7, default='#000000',
        validators=[RegexValidator(
            r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$',
            'Usa un color hexadecimal válido, por ejemplo #1A1A1A.',
        )],
    )
    sku = models.CharField('SKU de variante', max_length=80, unique=True, blank=True)
    stock = models.PositiveIntegerField('Stock físico', default=0)
    reserved = models.PositiveIntegerField(
        'Reservado', default=0,
        help_text='Unidades comprometidas por órdenes pendientes de pago.',
    )
    is_active = models.BooleanField('Activa', default=True)

    objects = ProductVariantQuerySet.as_manager()

    class Meta:
        verbose_name = 'Variante'
        verbose_name_plural = 'Variantes'
        ordering = ['product', 'color', 'size']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'size', 'color'], name='unique_variant_combo',
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__lte=models.F('stock')),
                name='reserved_lte_stock',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'is_active']),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.get_size_display()} / {self.color}'

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = f'{self.product.sku}-{self.size}-{slugify(self.color)}'.upper()
        super().save(*args, **kwargs)

    @property
    def available_stock(self) -> int:
        """Unidades realmente vendibles."""
        return max(self.stock - self.reserved, 0)

    @property
    def label(self) -> str:
        return f'{self.get_size_display()} / {self.color}'


class StoreSettings(models.Model):
    """Datos de la tienda que el dueño edita desde el panel de administración.

    Es un registro único (singleton): siempre existe una sola fila con pk=1.
    Así, cambiar el nombre, el costo de envío o el WhatsApp no requiere tocar
    código ni volver a desplegar.
    """

    SINGLETON_PK = 1

    # -- Identidad ------------------------------------------------------------
    store_name = models.CharField('Nombre de la tienda', max_length=80, default='GYMFORGE')
    name_accent = models.CharField(
        'Parte destacada del logo', max_length=40, blank=True, default='FORGE',
        help_text='Final del nombre que se pinta en color. Ej.: en «GYMFORGE» '
                  'se destaca «FORGE». Déjalo vacío para no destacar nada.',
    )
    tagline = models.CharField(
        'Eslogan', max_length=120, default='Ropa deportiva premium',
        help_text='Aparece en el título de la portada y en buscadores.',
    )

    # -- Datos legales (Ley 19.496 del Consumidor) ---------------------------
    legal_name = models.CharField(
        'Razón social o nombre del titular', max_length=150, blank=True,
        help_text='Obligatorio para vender online en Chile. Se muestra en el pie de página.',
    )
    rut = models.CharField('RUT', max_length=20, blank=True, help_text='Ej.: 76.123.456-7')
    address = models.CharField('Dirección comercial', max_length=200, blank=True)

    # -- Contacto --------------------------------------------------------------
    contact_email = models.EmailField(
        'Email de la tienda', blank=True,
        help_text='Recibe los avisos de nuevas ventas y los mensajes del '
                  'formulario de contacto. También se muestra a los clientes.',
    )
    contact_phone = models.CharField('Teléfono', max_length=30, blank=True)
    whatsapp_number = models.CharField(
        'WhatsApp', max_length=20, blank=True,
        help_text='Con código de país y solo números, ej.: 56912345678. '
                  'Si lo completas aparece un botón de WhatsApp en la tienda.',
        validators=[RegexValidator(r'^\d{8,15}$', 'Solo números, con código de país. Ej.: 56912345678')],
    )
    instagram_url = models.URLField('Instagram', blank=True)
    facebook_url = models.URLField('Facebook', blank=True)
    tiktok_url = models.URLField('TikTok', blank=True)

    # -- Envíos ----------------------------------------------------------------
    shipping_cost = models.PositiveIntegerField(
        'Costo de despacho (CLP)', default=4990,
        help_text='Se cobra en cada compra bajo el monto de envío gratis. '
                  'Pon 0 si el despacho siempre es gratis.',
    )
    free_shipping_threshold = models.PositiveIntegerField(
        'Envío gratis desde (CLP)', default=60000,
        help_text='Compras desde este monto no pagan despacho. Pon 0 para '
                  'no ofrecer envío gratis.',
    )
    announcement_text = models.CharField(
        'Texto de la barra superior', max_length=160, blank=True,
        help_text='Déjalo vacío para mostrar automáticamente el mensaje de envío gratis.',
    )

    updated_at = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        verbose_name = 'Ajustes de la tienda'
        verbose_name_plural = 'Ajustes de la tienda'

    def __str__(self):
        return 'Ajustes de la tienda'

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # El registro es imprescindible: nunca se borra.
        return (0, {})

    @classmethod
    def load(cls) -> 'StoreSettings':
        """Devuelve los ajustes, creándolos con valores iniciales si faltan."""
        from django.conf import settings

        obj, _ = cls.objects.get_or_create(
            pk=cls.SINGLETON_PK,
            defaults={
                'store_name': settings.SITE_NAME,
                'shipping_cost': settings.SHIPPING_COST,
                'free_shipping_threshold': settings.FREE_SHIPPING_THRESHOLD,
            },
        )
        return obj

    @classmethod
    def for_request(cls, request) -> 'StoreSettings':
        """Ajustes memorizados en la petición: una sola consulta por página."""
        cached = getattr(request, '_store_settings', None)
        if cached is None:
            cached = cls.load()
            try:
                request._store_settings = cached
            except AttributeError:
                pass
        return cached

    # -- Derivados -------------------------------------------------------------
    @property
    def free_shipping_enabled(self) -> bool:
        return self.free_shipping_threshold > 0

    @property
    def has_legal_info(self) -> bool:
        return bool(self.legal_name and self.rut)

    @property
    def whatsapp_url(self) -> str:
        return f'https://wa.me/{self.whatsapp_number}' if self.whatsapp_number else ''

    @property
    def logo_parts(self) -> tuple[str, str]:
        """Divide el nombre en (parte normal, parte destacada)."""
        accent = self.name_accent.strip()
        if accent and self.store_name.endswith(accent) and accent != self.store_name:
            return self.store_name[:-len(accent)], accent
        return self.store_name, ''
