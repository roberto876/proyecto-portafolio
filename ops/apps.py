from django.apps import AppConfig


class OpsConfig(AppConfig):
    """Operación de la tienda: salud, tareas programadas y diagnóstico."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ops'
    verbose_name = 'Operación'
