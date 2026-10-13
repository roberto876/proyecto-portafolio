"""Administración de transacciones de pago.

Las transacciones son un registro de auditoría: se consultan, nunca se
editan. Permitir modificarlas a mano abriría la puerta a marcar una orden
como pagada sin que exista un pago real.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import PaymentStatus, PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['buy_order', 'created_at', 'status_badge', 'amount_display',
                    'payment_type_display', 'masked_card', 'authorization_code']
    list_filter = ['status', 'provider', 'created_at']
    search_fields = ['buy_order', 'token', 'authorization_code',
                     'order__customer_email']
    date_hierarchy = 'created_at'
    list_select_related = ['order']

    # Todo es de solo lectura, sin excepción.
    readonly_fields = [
        'order', 'provider', 'token', 'buy_order', 'session_id', 'amount',
        'status', 'response_code', 'authorization_code', 'payment_type_code',
        'installments_number', 'card_last_digits', 'transaction_date',
        'raw_response', 'created_at', 'updated_at',
    ]
    fieldsets = (
        ('Transacción', {
            'fields': ('order', 'provider', 'buy_order', 'session_id',
                       'amount', 'created_at', 'updated_at'),
        }),
        ('Resultado', {
            'fields': ('status', 'response_code', 'authorization_code',
                       'payment_type_code', 'installments_number',
                       'card_last_digits', 'transaction_date'),
        }),
        ('Auditoría', {
            'fields': ('token', 'raw_response'),
            'classes': ('collapse',),
            'description': 'Respuesta saneada: no contiene datos de tarjeta.',
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Estado', ordering='status')
    def status_badge(self, obj):
        colors = {
            PaymentStatus.AUTHORIZED: '#27ae60',
            PaymentStatus.REJECTED: '#c0392b',
            PaymentStatus.CANCELLED: '#7f8c8d',
            PaymentStatus.EXPIRED: '#95a5a6',
            PaymentStatus.ERROR: '#e67e22',
            PaymentStatus.CREATED: '#2980b9',
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.status, '#333'), obj.get_status_display(),
        )

    @admin.display(description='Monto', ordering='amount')
    def amount_display(self, obj):
        return obj.amount_formatted
