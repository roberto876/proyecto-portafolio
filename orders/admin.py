"""Administración de órdenes.

Las órdenes son documentos contables: el admin permite gestionar el estado
logístico, pero no reescribir importes ni datos de la compra.
"""
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Order, OrderItem, OrderStatus
from .services import mark_as_cancelled


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    # Las líneas son un snapshot histórico: se consultan, no se editan.
    fields = ['product_name', 'sku', 'size', 'color', 'unit_price',
              'quantity', 'subtotal']
    readonly_fields = ['product_name', 'sku', 'size', 'color', 'unit_price',
                       'quantity', 'subtotal']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'created_at', 'customer_full_name',
                    'status_badge', 'total_display', 'stock_state', 'paid_at']
    list_filter = ['status', 'stock_committed', 'created_at', 'shipping_region']
    search_fields = ['order_number', 'customer_email', 'customer_first_name',
                     'customer_last_name', 'customer_phone']
    date_hierarchy = 'created_at'
    inlines = [OrderItemInline]
    list_select_related = ['user']
    actions = ['mark_processing', 'mark_shipped', 'mark_delivered', 'cancel_orders',
               'export_csv']

    @admin.action(description='Exportar a Excel (CSV)')
    def export_csv(self, request, queryset):
        """Descarga las órdenes seleccionadas para contabilidad o despacho.

        Separador «;» y BOM UTF-8: así Excel en español abre el archivo con
        columnas y tildes correctas con doble clic.
        """
        import csv

        from django.http import HttpResponse
        from django.utils import timezone

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f'ordenes-{timezone.localdate():%Y%m%d}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.write('﻿')

        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'Orden', 'Fecha', 'Estado', 'Cliente', 'Email', 'Teléfono', 'Región',
            'Comuna', 'Dirección', 'Productos', 'Subtotal', 'Despacho', 'Total',
            'Pagada el',
        ])
        for order in queryset.prefetch_related('items').order_by('-created_at'):
            products = ' | '.join(
                f'{item.quantity} x {item.product_name} ({item.size}/{item.color})'
                for item in order.items.all()
            )
            writer.writerow([
                order.order_number,
                timezone.localtime(order.created_at).strftime('%d-%m-%Y %H:%M'),
                order.get_status_display(),
                order.customer_full_name,
                order.customer_email,
                order.customer_phone,
                order.shipping_region,
                order.shipping_commune,
                f'{order.shipping_address} {order.shipping_number} {order.shipping_extra}'.strip(),
                products,
                order.subtotal,
                order.shipping_cost,
                order.total,
                timezone.localtime(order.paid_at).strftime('%d-%m-%Y %H:%M') if order.paid_at else '',
            ])
        return response

    # Solo el estado es editable: importes, datos del comprador e inventario
    # los gestiona la capa de servicios.
    readonly_fields = [
        'order_number', 'user', 'customer_first_name', 'customer_last_name',
        'customer_email', 'customer_phone', 'shipping_region',
        'shipping_commune', 'shipping_address', 'shipping_number',
        'shipping_extra', 'subtotal', 'shipping_cost', 'total',
        'stock_reserved', 'stock_committed', 'created_at', 'updated_at',
        'paid_at',
    ]
    fieldsets = (
        ('Orden', {
            'fields': ('order_number', 'status', 'user', 'created_at',
                       'updated_at', 'paid_at'),
        }),
        ('Comprador', {
            'fields': ('customer_first_name', 'customer_last_name',
                       'customer_email', 'customer_phone'),
        }),
        ('Despacho', {
            'fields': ('shipping_region', 'shipping_commune', 'shipping_address',
                       'shipping_number', 'shipping_extra'),
        }),
        ('Importes', {
            'fields': ('subtotal', 'shipping_cost', 'total'),
        }),
        ('Inventario', {
            'fields': ('stock_reserved', 'stock_committed'),
            'description': 'Gestionado automáticamente por el flujo de pago.',
        }),
    )

    def has_add_permission(self, request):
        # Las órdenes nacen del checkout, nunca a mano.
        return False

    def has_delete_permission(self, request, obj=None):
        # Borrar una orden pagada rompería la trazabilidad contable.
        return False

    @admin.display(description='Cliente')
    def customer_full_name(self, obj):
        return obj.customer_full_name

    @admin.display(description='Total', ordering='total')
    def total_display(self, obj):
        return obj.total_formatted

    @admin.display(description='Estado', ordering='status')
    def status_badge(self, obj):
        colors = {
            OrderStatus.PENDING_PAYMENT: '#e67e22',
            OrderStatus.PAID: '#27ae60',
            OrderStatus.PROCESSING: '#2980b9',
            OrderStatus.SHIPPED: '#8e44ad',
            OrderStatus.DELIVERED: '#16a085',
            OrderStatus.PAYMENT_REJECTED: '#c0392b',
            OrderStatus.CANCELLED: '#7f8c8d',
            OrderStatus.REFUNDED: '#d35400',
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.status, '#333'), obj.get_status_display(),
        )

    @admin.display(description='Inventario')
    def stock_state(self, obj):
        if obj.stock_committed:
            return 'Descontado'
        if obj.stock_reserved:
            return 'Reservado'
        return 'Liberado'

    def _advance(self, request, queryset, status, label):
        """Avanza el estado logístico solo de órdenes ya pagadas."""
        eligible = queryset.filter(status__in=[
            OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED,
        ])
        updated = eligible.update(status=status)
        skipped = queryset.count() - eligible.count()
        self.message_user(request, f'{updated} orden(es) marcada(s) como {label}.')
        if skipped:
            self.message_user(
                request,
                f'{skipped} orden(es) omitida(s): solo se avanza el estado de '
                'órdenes pagadas.',
                level=messages.WARNING,
            )

    @admin.action(description='Marcar como en preparación')
    def mark_processing(self, request, queryset):
        self._advance(request, queryset, OrderStatus.PROCESSING, 'en preparación')

    @admin.action(description='Marcar como enviada')
    def mark_shipped(self, request, queryset):
        self._advance(request, queryset, OrderStatus.SHIPPED, 'enviada')

    @admin.action(description='Marcar como entregada')
    def mark_delivered(self, request, queryset):
        self._advance(request, queryset, OrderStatus.DELIVERED, 'entregada')

    @admin.action(description='Cancelar y liberar stock')
    def cancel_orders(self, request, queryset):
        cancelled = 0
        for order in queryset:
            # Pasa por el servicio para que la liberación de stock sea correcta.
            if mark_as_cancelled(order):
                cancelled += 1
        self.message_user(
            request,
            f'{cancelled} orden(es) cancelada(s) y su stock liberado. '
            'Las órdenes ya pagadas no se cancelan desde aquí.',
        )
