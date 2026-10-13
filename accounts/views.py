"""Vistas de cuenta de usuario.

La autenticación usa exclusivamente el sistema de Django: las contraseñas se
almacenan con el hasher configurado y nunca se manipulan a mano.
"""
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import PasswordResetView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from orders.regions import REGIONS
from store.models import StoreSettings

from .forms import LoginForm, RegistrationForm, UserProfileForm


class StorePasswordResetView(PasswordResetView):
    """Recuperación de contraseña con el nombre de la tienda en el correo.

    El correo se renderiza sin los context processors, así que el nombre
    editable de la tienda se inyecta explícitamente.
    """

    def form_valid(self, form):
        self.extra_email_context = {
            'store_name': StoreSettings.for_request(self.request).store_name,
        }
        return super().form_valid(form)


def _safe_redirect_target(request, fallback='store:home') -> str:
    """Devuelve el destino de ``next`` solo si apunta a este mismo sitio.

    Sin esta validación, ``?next=https://sitio-malicioso`` convertiría el
    login en un redirector abierto para campañas de phishing.
    """
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
        url=target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse(fallback)


def register_view(request):
    """Registro de una cuenta nueva."""
    if request.user.is_authenticated:
        return redirect('store:home')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(
                request, f'¡Bienvenido/a, {user.first_name or user.username}!',
            )
            return redirect(_safe_redirect_target(request))
        messages.error(request, 'Revisa los datos marcados en rojo.')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {
        'form': form,
        'page_title': 'Crear cuenta',
        'noindex': True,
    })


def login_view(request):
    """Inicio de sesión."""
    if request.user.is_authenticated:
        return redirect('store:home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(
                request, f'Hola de nuevo, {user.first_name or user.username}.',
            )
            return redirect(_safe_redirect_target(request))
        messages.error(request, 'Usuario o contraseña incorrectos.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {
        'form': form,
        'next': request.GET.get('next', ''),
        'page_title': 'Iniciar sesión',
        'noindex': True,
    })


@require_POST
def logout_view(request):
    """Cierre de sesión.

    Solo por POST: un GET permitiría cerrar la sesión del usuario desde un
    enlace o una imagen en otro sitio.
    """
    logout(request)
    messages.info(request, 'Sesión cerrada.')
    return redirect('store:home')


@login_required
def profile_view(request):
    """Datos personales y dirección predeterminada."""
    profile = request.user.profile

    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil actualizado.')
            return redirect('accounts:profile')
        messages.error(request, 'Revisa los datos marcados en rojo.')
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    return render(request, 'accounts/profile.html', {
        'form': form,
        'regions_json': dict(REGIONS),
        'page_title': 'Mi perfil',
        'noindex': True,
    })


@login_required
def password_change(request):
    """Cambio de contraseña del usuario autenticado."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Mantiene la sesión activa tras rotar el hash de la contraseña.
            update_session_auth_hash(request, user)
            messages.success(request, 'Contraseña actualizada.')
            return redirect('accounts:profile')
        messages.error(request, 'Revisa los datos marcados en rojo.')
    else:
        form = PasswordChangeForm(request.user)

    for field in form.fields.values():
        field.widget.attrs.setdefault('class', 'form-input')

    return render(request, 'accounts/password_change.html', {
        'form': form,
        'page_title': 'Cambiar contraseña',
        'noindex': True,
    })
