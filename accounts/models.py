"""Perfil extendido del usuario.

No se define un modelo de usuario propio: se usa ``django.contrib.auth.User``
y se le asocia un perfil con la dirección de despacho predeterminada.
"""
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """Datos de contacto y despacho asociados a una cuenta."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='profile', verbose_name='Usuario',
    )
    phone = models.CharField('Teléfono', max_length=20, blank=True)
    region = models.CharField('Región', max_length=100, blank=True)
    commune = models.CharField('Comuna', max_length=100, blank=True)
    address = models.CharField('Dirección', max_length=200, blank=True)
    address_number = models.CharField('Número', max_length=20, blank=True)
    created_at = models.DateTimeField('Creado', auto_now_add=True)
    updated_at = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        verbose_name = 'Perfil de usuario'
        verbose_name_plural = 'Perfiles de usuario'

    def __str__(self):
        return f'Perfil de {self.user.username}'

    @property
    def has_address(self) -> bool:
        return bool(self.region and self.commune and self.address)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    """Crea el perfil al registrar un usuario.

    Se usa ``get_or_create`` para que la señal sea idempotente y para que los
    usuarios creados antes de existir este modelo (por ejemplo con
    ``createsuperuser``) también obtengan su perfil.
    """
    UserProfile.objects.get_or_create(user=instance)
