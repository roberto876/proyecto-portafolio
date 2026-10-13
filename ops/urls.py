from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('salud/', views.health, name='health'),
    # La ruta debe coincidir exactamente con la de vercel.json, con la barra
    # final: las tareas de Vercel no siguen redirecciones.
    path('cron/mantenimiento/', views.cron_maintenance, name='cron_maintenance'),
]
