"""Mantenimiento manual de la tienda.

Uso::

    python manage.py mantenimiento_tienda

Libera el stock de las órdenes abandonadas y resuelve los pagos que quedaron
a medio confirmar. En Vercel lo hace solo el cron diario; este comando sirve
para ejecutarlo a mano cuando se necesite.
"""
from django.core.management.base import BaseCommand

from ops.maintenance import run_maintenance


class Command(BaseCommand):
    help = 'Libera reservas de órdenes abandonadas y reconcilia pagos atascados.'

    def handle(self, *args, **options):
        summary = run_maintenance()
        self.stdout.write(self.style.SUCCESS(
            f'Listo. Reservas liberadas: {summary["reservas_liberadas"]}. '
            f'Pagos reconciliados: {summary["pagos_reconciliados"]}.'
        ))
