"""Tareas de mantenimiento compartidas por el cron y el comando manual."""
from orders.services import release_expired_orders
from payments.services import reconcile_stuck_payments


def run_maintenance() -> dict[str, int]:
    """Ejecuta el mantenimiento completo y devuelve un resumen.

    Ambas tareas son idempotentes: da igual si el cron se dispara dos veces.
    """
    return {
        'reservas_liberadas': release_expired_orders(),
        'pagos_reconciliados': reconcile_stuck_payments(),
    }
