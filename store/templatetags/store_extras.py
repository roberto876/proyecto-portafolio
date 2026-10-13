"""Filtros y tags de presentación de la tienda."""
from django import template
from django.utils.http import urlencode

from store.models import format_clp

register = template.Library()


@register.filter(name='clp')
def clp(value) -> str:
    """Formatea un entero como precio chileno: ``24990`` -> ``$24.990``."""
    try:
        return format_clp(int(value))
    except (TypeError, ValueError):
        return '$0'


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Devuelve la query string actual con los parámetros indicados sustituidos.

    Permite paginar u ordenar sin perder los filtros activos::

        <a href="?{% query_replace pagina=2 %}">Siguiente</a>
    """
    request = context.get('request')
    params = request.GET.copy() if request else {}
    if hasattr(params, 'copy'):
        params = params.copy()

    for key, value in kwargs.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value

    return urlencode(sorted(params.items())) if params else ''
