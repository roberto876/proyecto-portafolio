from django.urls import path

from . import views

app_name = 'cart'

urlpatterns = [
    path('', views.cart_detail, name='detail'),
    path('agregar/', views.cart_add, name='add'),
    path('actualizar/', views.cart_update, name='update'),
    path('eliminar/', views.cart_remove, name='remove'),
    path('vaciar/', views.cart_clear, name='clear'),
    path('estado/', views.cart_state, name='state'),
]
