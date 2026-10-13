"""Endpoints operativos: salud del sitio y tarea programada de Vercel."""
import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .maintenance import run_maintenance

logger = logging.getLogger('orders')


@never_cache
@require_GET
def health(request):
    """Comprueba que la aplicación y la base de datos respondan.

    Pensado para monitores externos (UptimeRobot, Better Stack). No expone
    ningún dato interno.
    """
    try:
        connection.ensure_connection()
    except Exception:  # noqa: BLE001 - se informa como caída, sin detalles.
        logger.exception('Chequeo de salud: la base de datos no responde')
        return JsonResponse({'ok': False, 'base_de_datos': 'error'}, status=503)
    return JsonResponse({'ok': True, 'base_de_datos': 'ok'})


@never_cache
@require_GET
def cron_maintenance(request):
    """Tarea diaria que invoca Vercel Cron.

    Vercel envía ``Authorization: Bearer <CRON_SECRET>`` cuando la variable
    CRON_SECRET existe en el proyecto. Sin ella el endpoint queda cerrado, así
    que nadie de fuera puede dispararlo.
    """
    secret = settings.CRON_SECRET
    provided = request.headers.get('Authorization', '')
    if not secret or not constant_time_compare(provided, f'Bearer {secret}'):
        return JsonResponse({'ok': False}, status=401)

    summary = run_maintenance()
    logger.info('Mantenimiento programado: %s', summary)
    return JsonResponse({'ok': True, **summary})


def store_status(request):
    """Página «Estado de la tienda» del panel (solo personal autorizado).

    Se registra envuelta en ``admin.site.admin_view``, que exige sesión de
    administrador.
    """
    from django.contrib import admin
    from django.shortcuts import render

    from .diagnostics import run_checks, summary

    checks = run_checks()
    return render(request, 'ops/diagnostico.html', {
        **admin.site.each_context(request),
        'title': 'Estado de la tienda',
        'checks': checks,
        'overall': summary(checks),
    })
