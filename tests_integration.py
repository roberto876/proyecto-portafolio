"""Pruebas de integración del recorrido completo de compra.

Recorren el flujo tal como lo haría una persona: catálogo, carrito, checkout,
pago y confirmación, verificando la consistencia entre carrito, orden,
inventario y transacción.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderStatus
from payments.models import PaymentStatus, PaymentTransaction
from payments.tests import FakeGateway, webpay_response
from store.models import Category, Product, ProductVariant, Size

CHECKOUT = {
    'first_name': 'Ana', 'last_name': 'Soto', 'email': 'ana@test.cl',
    'phone': '+56912345678', 'region': 'Metropolitana de Santiago',
    'commune': 'Providencia', 'address': 'Av. Providencia',
    'address_number': '1234', 'extra': 'Depto 42',
}


class FullPurchaseFlowTests(TestCase):
    """Recorrido completo: del catálogo a la confirmación de pago."""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=cls.category, name='Polera Integracion', price=25000,
            is_featured=True, main_image='https://example.test/p.jpg',
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=10,
        )

    def _pay(self, order, *, approved=True):
        """Simula el ciclo completo de pago contra un doble de Transbank.

        El doble se reutiliza entre llamadas para que cada reintento reciba un
        token distinto, igual que hace Transbank.
        """
        gateway = getattr(self, '_gateway', None)
        if gateway is None:
            gateway = self._gateway = FakeGateway()
        gateway.commit_response = webpay_response(
            amount=order.total,
            buy_order=order.order_number,
            status='AUTHORIZED' if approved else 'FAILED',
            response_code=0 if approved else -1,
        )
        with patch('payments.services.get_gateway', return_value=gateway):
            self.client.get(reverse('payments:start', args=[order.order_number]))
            # Cada intento crea su propia transacción: se usa la más reciente.
            token = PaymentTransaction.objects.filter(order=order).latest(
                'created_at'
            ).token
            response = self.client.get(
                reverse('payments:return'), {'token_ws': token},
            )
        return response

    def test_recorrido_completo_con_pago_aprobado(self):
        # 1. El visitante llega a la portada.
        self.assertEqual(self.client.get(reverse('store:home')).status_code, 200)

        # 2. Explora el catálogo.
        self.assertEqual(
            self.client.get(reverse('store:product_list')).status_code, 200,
        )

        # 3. Abre la ficha del producto.
        self.assertEqual(
            self.client.get(self.product.get_absolute_url()).status_code, 200,
        )

        # 4. Agrega dos unidades al carrito.
        add = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 2},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(add.json()['cart']['count'], 2)

        # 5. Revisa el carrito.
        cart_page = self.client.get(reverse('cart:detail'))
        self.assertContains(cart_page, 'Polera Integracion')

        # 6. Completa el checkout.
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()
        self.assertEqual(order.subtotal, 50000)
        self.assertEqual(order.status, OrderStatus.PENDING_PAYMENT)

        # El stock quedó reservado, no descontado.
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 10)
        self.assertEqual(self.variant.reserved, 2)

        # 7. Paga y vuelve desde Webpay.
        response = self._pay(order)
        self.assertTrue(response['Location'].startswith(
            reverse('payments:success', args=[order.order_number])
        ))

        # 8. La orden queda pagada y el stock descontado.
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)
        self.assertIsNotNone(order.paid_at)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 8)
        self.assertEqual(self.variant.reserved, 0)

        # 9. El carrito quedó vacío.
        self.assertEqual(
            self.client.get(reverse('cart:state')).json()['cart']['count'], 0,
        )

        # 10. La página de confirmación muestra los datos correctos.
        success = self.client.get(
            reverse('payments:success', args=[order.order_number])
        )
        self.assertContains(success, order.order_number)
        self.assertContains(success, 'Compra realizada con éxito')

    def test_recorrido_con_pago_rechazado_no_descuenta_stock(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 3,
        })
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()

        response = self._pay(order, approved=False)
        self.assertTrue(response['Location'].startswith(
            reverse('payments:failure', args=[order.order_number])
        ))

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 10)
        self.assertEqual(self.variant.reserved, 0)

    def test_reintento_de_pago_tras_rechazo_funciona(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()

        self._pay(order, approved=False)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)

        # Segundo intento, esta vez aprobado.
        self._pay(order, approved=True)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 8)
        self.assertEqual(PaymentTransaction.objects.filter(order=order).count(), 2)
        self.assertEqual(
            PaymentTransaction.objects.filter(
                order=order, status=PaymentStatus.AUTHORIZED,
            ).count(),
            1,
        )

    def test_usuario_registrado_ve_la_orden_en_su_historial(self):
        User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.client.login(username='ana', password='ClaveSegura123')

        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 1,
        })
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()
        self._pay(order)

        historial = self.client.get(reverse('orders:list'))
        self.assertContains(historial, order.order_number)

    def test_dos_compradores_no_pueden_llevarse_el_mismo_ultimo_producto(self):
        """Consistencia de inventario ante compras simultáneas."""
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=1)

        comprador_a = self.client_class()
        comprador_b = self.client_class()

        # A llena el carrito y crea la orden: reserva la única unidad.
        comprador_a.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 1,
        })
        comprador_a.post(reverse('orders:checkout'), CHECKOUT)
        self.assertEqual(Order.objects.count(), 1)

        # B ya no puede agregarla al carrito.
        respuesta_b = comprador_b.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 1},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(respuesta_b.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.available_stock, 0)

    def test_el_callback_duplicado_no_cobra_dos_veces(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()

        gateway = FakeGateway(commit_response=webpay_response(
            amount=order.total, buy_order=order.order_number,
        ))
        with patch('payments.services.get_gateway', return_value=gateway):
            self.client.get(reverse('payments:start', args=[order.order_number]))
            token = PaymentTransaction.objects.get(order=order).token
            # Transbank reintenta el callback.
            self.client.get(reverse('payments:return'), {'token_ws': token})
            self.client.get(reverse('payments:return'), {'token_ws': token})
            self.client.get(reverse('payments:return'), {'token_ws': token})

        self.assertEqual(len(gateway.commit_calls), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 8)

    def test_anular_en_webpay_libera_el_stock(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 4,
        })
        self.client.post(reverse('orders:checkout'), CHECKOUT)
        order = Order.objects.get()

        gateway = FakeGateway(commit_response=webpay_response(
            amount=order.total, buy_order=order.order_number,
        ))
        with patch('payments.services.get_gateway', return_value=gateway):
            self.client.get(reverse('payments:start', args=[order.order_number]))

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 4)

        # El comprador pulsa "anular" en el formulario de Webpay. Transbank
        # devuelve el token de la transacción en TBK_TOKEN.
        payment = PaymentTransaction.objects.get(order=order)
        self.client.post(reverse('payments:return'), {
            'TBK_TOKEN': payment.token,
            'TBK_ORDEN_COMPRA': order.order_number,
            'TBK_ID_SESION': payment.session_id,
        })

        # La orden queda reintentable (no cancelada) y el stock, libre.
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)
        self.assertTrue(order.can_retry_payment)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 0)
        self.assertEqual(self.variant.stock, 10)


class AllPagesRenderTests(TestCase):
    """Ninguna página pública debe romperse con el catálogo cargado."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=category, name='Polera Render', price=19990,
            compare_price=24990, is_featured=True,
        )
        ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=5,
        )

    def test_paginas_publicas_responden_200(self):
        rutas = [
            reverse('store:home'),
            reverse('store:product_list'),
            reverse('store:offers'),
            reverse('store:about'),
            reverse('store:contact'),
            reverse('store:terms'),
            reverse('store:privacy'),
            reverse('store:shipping'),
            reverse('cart:detail'),
            reverse('accounts:login'),
            reverse('accounts:register'),
            reverse('accounts:password_reset'),
            self.product.get_absolute_url(),
            '/sitemap.xml',
            '/robots.txt',
        ]
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 200)

    def test_catalogo_con_todas_las_combinaciones_de_filtros(self):
        combinaciones = [
            {'categoria': 'poleras'},
            {'genero': 'H'}, {'genero': 'M'}, {'genero': 'U'},
            {'talla': 'M'}, {'talla': 'XXL'},
            {'color': 'Negro'}, {'color': 'Inexistente'},
            {'precio_min': '1000'}, {'precio_max': '100000'},
            {'precio_min': '1000', 'precio_max': '100000'},
            {'orden': 'recientes'}, {'orden': 'precio_asc'},
            {'orden': 'precio_desc'}, {'orden': 'vendidos'}, {'orden': 'nombre'},
            {'q': 'polera'}, {'q': ''},
            {'pagina': '1'}, {'pagina': '999'}, {'pagina': 'abc'},
            {'categoria': 'poleras', 'genero': 'H', 'orden': 'precio_asc'},
        ]
        for params in combinaciones:
            with self.subTest(params=params):
                response = self.client.get(reverse('store:product_list'), params)
                self.assertEqual(response.status_code, 200)

    def test_entradas_maliciosas_no_rompen_el_catalogo(self):
        ataques = [
            {'q': "<script>alert('xss')</script>"},
            {'q': "'; DROP TABLE store_product; --"},
            {'categoria': '../../etc/passwd'},
            {'precio_min': 'NaN'},
            {'precio_max': '1e999'},
            {'orden': '__import__("os")'},
            {'talla': 'M' * 1000},
            {'color': '%00'},
            {'pagina': '-1'},
        ]
        for params in ataques:
            with self.subTest(params=params):
                response = self.client.get(reverse('store:product_list'), params)
                self.assertEqual(response.status_code, 200)

    def test_el_xss_en_la_busqueda_se_escapa(self):
        response = self.client.get(
            reverse('store:product_list'), {'q': "<script>alert(1)</script>"},
        )
        self.assertNotContains(response, '<script>alert(1)</script>')
