"""Administración del catálogo, el inventario y los ajustes de la tienda.

Pensado para alguien sin conocimientos técnicos: textos de ayuda en cada
campo, subida de fotos, creación de variantes en bloque y selector de color.
"""
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, F
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from .models import Category, Product, ProductImage, ProductVariant, Size, StoreSettings
from .storage import StorageError, is_configured, upload_image
from .variants import create_variant_grid, parse_colors

UPLOAD_HELP = (
    'Sube una foto JPG, PNG o WebP de hasta 4 MB. Si subes un archivo, '
    'reemplaza al enlace de arriba.'
)
UPLOAD_DISABLED_HELP = (
    'La subida de fotos no está activada: pega el enlace de la imagen arriba '
    '(ver GUIA.md, Parte 2, paso 7).'
)


def _upload_field(label: str) -> forms.FileField:
    """Campo de subida de imagen con la ayuda adecuada según la configuración."""
    return forms.FileField(
        label=label,
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
        help_text=UPLOAD_HELP if is_configured() else UPLOAD_DISABLED_HELP,
    )


class ImageUploadMixin:
    """Sube la imagen durante la validación para mostrar errores en el campo.

    ``upload_field`` es el campo de archivo y ``url_field`` el campo de URL del
    modelo que recibe la dirección pública resultante.
    """

    upload_field = ''
    url_field = ''
    upload_folder = 'productos'
    image_required = False

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get(self.upload_field)
        if upload and not self.errors:
            try:
                cleaned[self.url_field] = upload_image(upload, folder=self.upload_folder)
            except StorageError as exc:
                self.add_error(self.upload_field, str(exc))
        if self.image_required and not cleaned.get(self.url_field) and not self.errors:
            self.add_error(self.url_field, 'Sube una foto o pega el enlace de una.')
        return cleaned


# ---------------------------------------------------------------------------
# Ajustes de la tienda
# ---------------------------------------------------------------------------
@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    """Ajustes únicos de la tienda: siempre se edita el mismo registro."""

    fieldsets = (
        ('Identidad', {
            'fields': ('store_name', 'name_accent', 'tagline'),
        }),
        ('Datos legales', {
            'fields': ('legal_name', 'rut', 'address'),
            'description': 'La Ley del Consumidor exige mostrar quién vende. '
                           'Estos datos aparecen en el pie de página.',
        }),
        ('Contacto y redes', {
            'fields': ('contact_email', 'contact_phone', 'whatsapp_number',
                       'instagram_url', 'facebook_url', 'tiktok_url'),
        }),
        ('Despacho', {
            'fields': ('shipping_cost', 'free_shipping_threshold', 'announcement_text'),
        }),
    )

    def has_add_permission(self, request):
        return not StoreSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # No hay lista que mostrar: se abre directamente el formulario.
        settings_obj = StoreSettings.load()
        return redirect(reverse('admin:store_storesettings_change', args=[settings_obj.pk]))


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------
class CategoryAdminForm(ImageUploadMixin, forms.ModelForm):
    upload_field = 'image_upload'
    url_field = 'image'
    upload_folder = 'categorias'

    image_upload = _upload_field('Subir foto de la categoría')

    class Meta:
        model = Category
        fields = '__all__'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ['name', 'product_count', 'is_active', 'sort_order']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'sort_order']
    readonly_fields = ['created_at', 'updated_at']
    fields = ['name', 'slug', 'description', 'image', 'image_upload', 'is_active',
              'sort_order', 'created_at', 'updated_at']

    def get_queryset(self, request):
        # Anotar el conteo evita una consulta por fila en el listado.
        return super().get_queryset(request).annotate(_product_count=Count('products'))

    @admin.display(description='Productos', ordering='_product_count')
    def product_count(self, obj):
        return obj._product_count


# ---------------------------------------------------------------------------
# Productos
# ---------------------------------------------------------------------------
class ProductImageInlineForm(ImageUploadMixin, forms.ModelForm):
    upload_field = 'image_upload'
    url_field = 'image'
    image_required = True

    image_upload = _upload_field('Subir foto')

    class Meta:
        model = ProductImage
        fields = ['image', 'image_upload', 'alt_text', 'sort_order']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # La URL deja de ser obligatoria: basta con subir un archivo.
        self.fields['image'].required = False

    def has_changed(self):
        # Una fila vacía del inline no debe exigir foto.
        return super().has_changed()

    def clean(self):
        if not self.has_changed():
            return self.cleaned_data
        return super().clean()


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    form = ProductImageInlineForm
    extra = 1
    verbose_name = 'Foto adicional'
    verbose_name_plural = 'Fotos adicionales (galería)'


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ['size', 'color', 'color_hex', 'stock', 'reserved',
              'available_stock_display', 'is_active', 'sku']
    # `reserved` lo gestiona el flujo de órdenes: editarlo a mano descuadraría
    # el inventario frente a las órdenes pendientes de pago.
    readonly_fields = ['reserved', 'available_stock_display', 'sku']
    verbose_name = 'Variante (talla y color)'
    verbose_name_plural = 'Variantes: una fila por combinación de talla y color'

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'color_hex':
            # Selector de color visual en lugar de escribir «#1A1A1A».
            kwargs['widget'] = forms.TextInput(attrs={'type': 'color'})
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description='Disponible')
    def available_stock_display(self, obj):
        if obj.pk is None:
            return '—'
        return obj.available_stock


class ProductAdminForm(ImageUploadMixin, forms.ModelForm):
    upload_field = 'main_image_upload'
    url_field = 'main_image'
    image_required = True

    main_image_upload = _upload_field('Subir foto principal')

    bulk_sizes = forms.MultipleChoiceField(
        label='Tallas a crear', choices=Size.choices, required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    bulk_colors = forms.CharField(
        label='Colores a crear', required=False,
        help_text='Separados por coma. Ej.: Negro, Blanco, Azul marino. El color '
                  'de la muestra se asigna solo (puedes ajustarlo después).',
    )
    bulk_stock = forms.IntegerField(
        label='Stock inicial de cada combinación', required=False,
        min_value=0, initial=10,
    )

    class Meta:
        model = Product
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        sizes, colors = cleaned.get('bulk_sizes'), cleaned.get('bulk_colors')
        if bool(sizes) != bool(colors and colors.strip()):
            raise forms.ValidationError(
                'Para crear variantes en bloque elige al menos una talla y escribe al menos un color.'
            )
        return cleaned


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ['thumbnail', 'name', 'category', 'gender', 'price_display',
                    'discount_display', 'stock_display', 'is_active', 'is_featured',
                    'sales_count']
    list_display_links = ['thumbnail', 'name']
    list_filter = ['is_active', 'is_featured', 'gender', 'category', 'created_at']
    search_fields = ['name', 'sku', 'description']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'is_featured']
    readonly_fields = ['created_at', 'updated_at', 'sales_count', 'image_preview']
    inlines = [ProductVariantInline, ProductImageInline]
    list_select_related = ['category']
    actions = ['mark_featured', 'unmark_featured', 'activate', 'deactivate']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Información', {
            'fields': ('name', 'slug', 'category', 'gender', 'description'),
        }),
        ('Precios', {
            'fields': ('price', 'compare_price', 'sku'),
            'description': 'Para mostrar un producto en oferta, pon el precio '
                           'anterior (más alto) en «Precio anterior». El SKU se '
                           'genera solo si lo dejas vacío.',
        }),
        ('Foto principal', {
            'fields': ('main_image', 'main_image_upload', 'image_preview'),
        }),
        ('Crear variantes rápido', {
            'fields': ('bulk_sizes', 'bulk_colors', 'bulk_stock'),
            'description': 'Marca las tallas y escribe los colores: al guardar se '
                           'crean todas las combinaciones que falten. Las que ya '
                           'existen no se modifican.',
        }),
        ('Estado', {
            'fields': ('is_active', 'is_featured'),
            'description': '«Activo» lo muestra en la tienda. «Destacado» lo pone en la portada.',
        }),
        ('Métricas', {
            'fields': ('sales_count', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('variants')

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sizes = form.cleaned_data.get('bulk_sizes') or []
        colors = parse_colors(form.cleaned_data.get('bulk_colors') or '')
        if sizes and colors:
            stock = form.cleaned_data.get('bulk_stock') or 0
            created = create_variant_grid(form.instance, sizes, colors, stock)
            self.message_user(
                request,
                f'Se crearon {created} variante(s) nuevas.' if created
                else 'Todas esas combinaciones ya existían: no se creó ninguna.',
                messages.SUCCESS if created else messages.INFO,
            )

    @admin.display(description='')
    def thumbnail(self, obj):
        if not obj.main_image:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="width:44px;height:56px;object-fit:cover;border-radius:4px">',
            obj.main_image,
        )

    @admin.display(description='Precio', ordering='price')
    def price_display(self, obj):
        return obj.price_formatted

    @admin.display(description='Descuento')
    def discount_display(self, obj):
        return f'-{obj.discount_percentage}%' if obj.is_on_sale else '—'

    @admin.display(description='Stock disponible')
    def stock_display(self, obj):
        total = obj.total_stock
        color = '#c0392b' if total == 0 else ('#e67e22' if total < 10 else '#27ae60')
        return format_html('<b style="color:{}">{}</b>', color, total)

    @admin.display(description='Vista previa')
    def image_preview(self, obj):
        if not obj.main_image:
            return 'Sin imagen'
        return format_html(
            '<img src="{}" alt="" style="max-height:180px;border-radius:8px">',
            obj.main_image,
        )

    @admin.action(description='Marcar como destacado')
    def mark_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} producto(s) destacado(s).')

    @admin.action(description='Quitar de destacados')
    def unmark_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} producto(s) sin destacar.')

    @admin.action(description='Activar (mostrar en la tienda)')
    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} producto(s) activado(s).')

    @admin.action(description='Desactivar (ocultar de la tienda)')
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} producto(s) desactivado(s).')


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------
class StockLevelFilter(admin.SimpleListFilter):
    """Filtra variantes por nivel de stock disponible."""

    title = 'nivel de stock'
    parameter_name = 'stock'

    def lookups(self, request, model_admin):
        return [('bajo', 'Stock bajo (3 o menos)'), ('agotado', 'Agotadas')]

    def queryset(self, request, queryset):
        if self.value() == 'bajo':
            return queryset.filter(stock__lte=F('reserved') + 3, stock__gt=F('reserved'))
        if self.value() == 'agotado':
            return queryset.filter(stock__lte=F('reserved'))
        return queryset


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Vista de inventario: permite ajustar stock sin abrir cada producto."""

    list_display = ['product', 'size', 'color', 'stock', 'reserved',
                    'available_display', 'is_active', 'sku']
    list_filter = [StockLevelFilter, 'is_active', 'size', 'product__category']
    search_fields = ['sku', 'product__name', 'color']
    list_editable = ['stock', 'is_active']
    list_select_related = ['product']
    readonly_fields = ['reserved']

    @admin.display(description='Disponible')
    def available_display(self, obj):
        return obj.available_stock


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'sort_order', 'alt_text']
    list_filter = ['product__category']
    search_fields = ['product__name', 'alt_text']
    list_select_related = ['product']
