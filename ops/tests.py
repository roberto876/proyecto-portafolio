"""Pruebas de operación: órdenes abandonadas, pagos atascados, cron y salud."""
from datetime import timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cart.cart import Cart
from orders.models import Order, OrderStatus
from orders.services import (
    SWEEP_CACHE_KEY,
    create_order_from_cart,
    maybe_release_expired_orders,
    release_expired_orders,
)
from payments.models import PaymentStatus, PaymentTransaction
from payments.services import confirm_transaction, reconcile_stuck_payments, start_transaction
from payments.tests import CHECKOUT, FakeGateway, webpay_response
from store.models import Category, Product, ProductVariant, Size


class MaintenanceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=category, name='Polera Ops', price=10000,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=10,
        )

    def setUp(self):
        cache.delete(SWEEP_CACHE_KEY)

    def make_order(self, quantity=2):
        request = type('Request', (), {})()
        client = self.client_class()
        client.get(reverse('store:home'))
        request.session = client.session
        cart = Cart(request)
        cart.add(self.variant.pk, quantity)
        return create_order_from_cart(cart=cart, data=CHECKOUT)

    def age(self, order, minutes):
        """Envejece una orden sin pasar por auto_now."""
        Order.objects.filter(pk=order.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes),
        )

    def reserved(self):
        self.variant.refresh_from_db()
        return self.variant.reserved


# ===========================================================================
# Órdenes abandonadas
# ===========================================================================
@override_settings(ORDER_RESERVATION_MINUTES=30)
class ReleaseExpiredOrdersTests(MaintenanceTestCase):
    def test_orden_abandonada_se_cancela_y_libera_stock(self):
        order = self.make_order(3)
        self.age(order, 45)

        self.assertEqual(release_expired_orders(), 1)

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.reserved(), 0)

    def test_orden_reciente_se_respeta(self):
        self.make_order(3)
        self.assertEqual(release_expired_orders(), 0)
        self.assertEqual(self.reserved(), 3)

    def test_orden_con_pago_reciente_se_respeta(self):
        """El comprador puede estar en pleno formulario de Webpay."""
        order = self.make_order(2)
        start_transaction(order, return_url='https://x.cl/r', gateway=FakeGateway())
        self.age(order, 45)

        self.assertEqual(release_expired_orders(), 0)
        self.assertEqual(self.reserved(), 2)

    def test_orden_con_pago_en_confirmacion_se_respeta(self):
        order = self.make_order(2)
        start_transaction(order, return_url='https://x.cl/r', gateway=FakeGateway())
        PaymentTransaction.objects.update(
            status=PaymentStatus.PROCESSING,
            created_at=timezone.now() - timedelta(hours=2),
        )
        self.age(order, 45)

        self.assertEqual(release_expired_orders(), 0)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PENDING_PAYMENT)

    def test_orden_pagada_nunca_se_toca(self):
        order = self.make_order(2)
        gateway = FakeGateway(commit_response=webpay_response(
            amount=order.total, buy_order=order.order_number,
        ))
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        confirm_transaction(PaymentTransaction.objects.get().token, gateway=gateway)
        self.age(order, 500)

        self.assertEqual(release_expired_orders(), 0)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)

    def test_es_idempotente(self):
        order = self.make_order(2)
        self.age(order, 45)
        self.assertEqual(release_expired_orders(), 1)
        self.assertEqual(release_expired_orders(), 0)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 10)

    def test_plazo_configurable(self):
        order = self.make_order(1)
        self.age(order, 10)
        self.assertEqual(release_expired_orders(older_than_minutes=5), 1)

    def test_barrido_oportunista_se_limita_por_minuto(self):
        first = self.make_order(1)
        self.age(first, 45)
        self.assertEqual(maybe_release_expired_orders(), 1)

        second = self.make_order(1)
        self.age(second, 45)
        # Dentro del mismo minuto no vuelve a barrer.
        self.assertEqual(maybe_release_expired_orders(), 0)

    def test_agregar_al_carrito_libera_reservas_vencidas(self):
        """Recorrido real: el último producto vuelve a estar a la venta."""
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=2)
        abandoned = self.make_order(2)
        self.age(abandoned, 45)

        response = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 2},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cart']['count'], 2)


# ===========================================================================
# Pagos atascados
# ===========================================================================
class ReconcileStuckPaymentsTests(MaintenanceTestCase):
    def stuck_payment(self, *, approved=True):
        order = self.make_order(2)
        gateway = FakeGateway(commit_response=webpay_response(
            amount=order.total,
            buy_order=order.order_number,
            status='AUTHORIZED' if approved else 'FAILED',
            response_code=0 if approved else -1,
        ))
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        PaymentTransaction.objects.update(
            status=PaymentStatus.PROCESSING,
            updated_at=timezone.now() - timedelta(minutes=30),
        )
        return order, gateway

    def test_pago_atascado_aprobado_se_marca_pagado(self):
        order, gateway = self.stuck_payment(approved=True)
        self.assertEqual(reconcile_stuck_payments(gateway=gateway), 1)

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 8)

    def test_pago_atascado_rechazado_libera_stock(self):
        order, gateway = self.stuck_payment(approved=False)
        self.assertEqual(reconcile_stuck_payments(gateway=gateway), 1)

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)
        self.assertEqual(self.reserved(), 0)

    def test_fallo_de_transbank_no_inventa_resultado(self):
        order, _ = self.stuck_payment()

        class BrokenGateway(FakeGateway):
            def status(self, token):
                from payments.transbank import PaymentGatewayError
                raise PaymentGatewayError('Transbank caído')

        self.assertEqual(reconcile_stuck_payments(gateway=BrokenGateway()), 0)
        self.assertEqual(
            PaymentTransaction.objects.get().status, PaymentStatus.PROCESSING,
        )

    def test_pago_en_confirmacion_reciente_no_se_toca(self):
        order, gateway = self.stuck_payment()
        PaymentTransaction.objects.update(updated_at=timezone.now())
        self.assertEqual(reconcile_stuck_payments(gateway=gateway), 0)

    def test_sin_pagos_atascados_no_llama_a_transbank(self):
        class ExplodingGateway:
            def status(self, token):
                raise AssertionError('No debió llamarse')

        self.assertEqual(reconcile_stuck_payments(gateway=ExplodingGateway()), 0)


# ===========================================================================
# Endpoints y comando
# ===========================================================================
class CronEndpointTests(MaintenanceTestCase):
    url = '/ops/cron/mantenimiento/'

    @override_settings(CRON_SECRET='')
    def test_sin_secreto_configurado_queda_cerrado(self):
        response = self.client.get(self.url, headers={'authorization': 'Bearer '})
        self.assertEqual(response.status_code, 401)

    @override_settings(CRON_SECRET='secreto-largo-de-prueba')
    def test_sin_cabecera_se_rechaza(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    @override_settings(CRON_SECRET='secreto-largo-de-prueba')
    def test_secreto_incorrecto_se_rechaza(self):
        response = self.client.get(
            self.url, headers={'authorization': 'Bearer otro-secreto'},
        )
        self.assertEqual(response.status_code, 401)

    @override_settings(CRON_SECRET='secreto-largo-de-prueba', ORDER_RESERVATION_MINUTES=30)
    def test_secreto_correcto_ejecuta_el_mantenimiento(self):
        order = self.make_order(2)
        self.age(order, 45)

        response = self.client.get(
            self.url, headers={'authorization': 'Bearer secreto-largo-de-prueba'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reservas_liberadas'], 1)

    @override_settings(CRON_SECRET='secreto-largo-de-prueba')
    def test_no_redirige(self):
        """Vercel Cron no sigue redirecciones: la ruta debe ser exacta."""
        response = self.client.get(
            self.url, headers={'authorization': 'Bearer secreto-largo-de-prueba'},
        )
        self.assertNotIn(response.status_code, (301, 302, 308))

    def test_la_ruta_coincide_con_vercel_json(self):
        import json
        from pathlib import Path
        config = json.loads(
            (Path(__file__).resolve().parent.parent / 'vercel.json').read_text()
        )
        paths = [cron['path'] for cron in config['crons']]
        self.assertIn(reverse('ops:cron_maintenance'), paths)

    def test_post_no_permitido(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)


class HealthAndCommandTests(MaintenanceTestCase):
    def test_salud_responde_ok(self):
        response = self.client.get(reverse('ops:health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'base_de_datos': 'ok'})

    def test_salud_no_se_cachea(self):
        response = self.client.get(reverse('ops:health'))
        self.assertIn('no-cache', response.get('Cache-Control', ''))

    @override_settings(ORDER_RESERVATION_MINUTES=30)
    def test_comando_de_mantenimiento(self):
        order = self.make_order(1)
        self.age(order, 45)
        out = StringIO()
        call_command('mantenimiento_tienda', stdout=out)
        self.assertIn('Reservas liberadas: 1', out.getvalue())
