"""Middleware de cabeceras de seguridad.

Añade una Content-Security-Policy y cabeceras complementarias que Django no
emite por sí mismo. Se implementa aquí (y no con una dependencia externa) para
mantener el proyecto con la menor superficie de dependencias posible.
"""
from django.conf import settings
from django.middleware.csrf import get_token


def _build_csp(directives: dict[str, list[str]]) -> str:
    """Serializa un diccionario de directivas a una cabecera CSP."""
    return '; '.join(
        f'{name} {" ".join(values)}' if values else name
        for name, values in directives.items()
    )


class SecurityHeadersMiddleware:
    """Aplica CSP y cabeceras de endurecimiento a cada respuesta."""

    #: Rutas cuyo CSP se relaja: el admin de Django usa estilos y scripts
    #: en línea que no podemos controlar.
    ADMIN_PREFIX = '/admin/'

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp_header = _build_csp(getattr(settings, 'CSP_DIRECTIVES', {}))

    #: Métodos en los que se garantiza la cookie CSRF.
    SAFE_METHODS = frozenset({'GET', 'HEAD'})

    def __call__(self, request):
        # El carrito se manipula por fetch() desde cualquier página, incluida
        # la ficha de producto, que no tiene formularios. Django solo emite la
        # cookie CSRF cuando una plantilla renderiza {% csrf_token %}, así que
        # sin esto un visitante nuevo recibiría 403 al agregar al carrito.
        if request.method in self.SAFE_METHODS:
            get_token(request)

        response = self.get_response(request)

        if self.csp_header and not request.path.startswith(self.ADMIN_PREFIX):
            response.setdefault('Content-Security-Policy', self.csp_header)

        response.setdefault(
            'Permissions-Policy',
            'geolocation=(), microphone=(), camera=(), payment=(), usb=()',
        )
        response.setdefault('X-Content-Type-Options', 'nosniff')
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')

        return response
