from django.urls import path

from . import views

app_name = 'payments'

urlpatterns = [
    path('iniciar/<str:order_number>/', views.start_payment, name='start'),
    # URL de retorno configurada en la transacción de Webpay.
    path('retorno/', views.payment_return, name='return'),
    path('exito/<str:order_number>/', views.payment_success, name='success'),
    path('rechazado/<str:order_number>/', views.payment_failure, name='failure'),
]
