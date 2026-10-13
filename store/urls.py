from django.urls import path

from . import views

app_name = 'store'

urlpatterns = [
    path('', views.home, name='home'),
    path('productos/', views.product_list, name='product_list'),
    path('ofertas/', views.offers, name='offers'),
    path('sobre-nosotros/', views.about, name='about'),
    path('contacto/', views.contact, name='contact'),
    path('terminos/', views.terms, name='terms'),
    path('privacidad/', views.privacy, name='privacy'),
    path('envios/', views.shipping, name='shipping'),
    # Endpoints AJAX (solo lectura, sin datos sensibles).
    path('api/productos/<int:product_id>/stock/', views.variant_stock, name='variant_stock'),
    path('api/buscar/', views.search_suggestions, name='search_suggestions'),
    # El detalle de producto va al final para no capturar las rutas anteriores.
    path('productos/<slug:slug>/', views.product_detail, name='product_detail'),
]
