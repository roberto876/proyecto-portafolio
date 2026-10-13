"""Administración de usuarios y perfiles."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil'
    fields = ['phone', 'region', 'commune', 'address', 'address_number']


class UserAdmin(BaseUserAdmin):
    """Usuario con su perfil y su historial de compras a la vista."""

    inlines = [UserProfileInline]
    list_display = ['username', 'email', 'first_name', 'last_name',
                    'order_count', 'is_staff', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_superuser', 'is_active', 'date_joined']

    @admin.display(description='Órdenes')
    def order_count(self, obj):
        return obj.orders.count()


# Se reemplaza el admin de usuario por defecto para incluir el perfil.
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone', 'region', 'commune']
    list_filter = ['region']
    search_fields = ['user__username', 'user__email', 'phone']
    list_select_related = ['user']
