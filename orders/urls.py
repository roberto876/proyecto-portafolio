from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('mis-pedidos/', views.order_list, name='list'),
    path('api/comunas/', views.communes_api, name='communes_api'),
    path('<str:order_number>/', views.order_detail, name='detail'),
]
