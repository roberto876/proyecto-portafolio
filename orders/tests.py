"""Pruebas de órdenes: creación, inventario, autorización y checkout."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.cart import Cart
from orders.forms import CheckoutForm
from orders.models import Order, OrderItem, OrderStatus, generate_order_number
from orders.regions import REGIONS, communes_for, is_valid_location
from orders.services import (
    InsufficientStockError,
    OrderError,
    commit_stock,
    create_order_from_cart,
    mark_as_cancelled,
    mark_as_paid,
    mark_as_rejected,
    release_stock,
)
from store.models import Category, Product, ProductVariant, Size

VALID_CHECKOUT = {
    'first_name': 'Ana',
    'last_name': 'Soto',
    'email': 'ana@test.cl',
    'phone': '+56912345678',
    'region': 'Metropolitana de Santiago',
    'commune': 'Providencia',
    'address': 'Av. Providencia',
    'address_number': '1234',
    'extra': 'Depto 42',
}


class OrderTestCase(TestCase):
    """Base con catálogo y utilidades para armar carritos."""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=cls.category, name='Polera Test', price=10000,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=10,
        )

    def build_cart(self, quantity=2, variant=None):
        """Devuelve un carrito real con una línea cargada."""
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))
        request.session = self.client.session
        cart = Cart(request)
        cart.add((variant or self.variant).pk, quantity)
        return cart

    def refresh_variant(self):
        self.variant.refresh_from_db()
        return self.variant


# ===========================================================================
# Modelo
# ===========================================================================
class OrderModelTests(OrderTestCase):
    def test_numero_de_orden_es_unico(self):
        numbers = {generate_order_number() for _ in range(200)}
        self.assertEqual(len(numbers), 200)

    def test_numero_de_orden_cabe_en_transbank(self):
        # Transbank limita buy_order a 26 caracteres.
        self.assertLessEqual(len(generate_order_number()), 26)

    def test_numero_de_orden_empieza_con_prefijo(self):
        self.assertTrue(generate_order_number().startswith('GF'))

    def test_nombre_completo_del_cliente(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertEqual(order.customer_full_name, 'Ana Soto')

    def test_direccion_completa_incluye_extra(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertIn('Depto 42', order.full_shipping_address)
        self.assertIn('Providencia', order.full_shipping_address)

    def test_direccion_completa_sin_extra(self):
        data = {**VALID_CHECKOUT, 'extra': ''}
        order = create_order_from_cart(cart=self.build_cart(), data=data)
        self.assertNotIn(', ,', order.full_shipping_address)

    def test_estado_inicial_es_pendiente(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertEqual(order.status, OrderStatus.PENDING_PAYMENT)
        self.assertTrue(order.is_pending_payment)
        self.assertFalse(order.is_paid)

    def test_puede_reintentar_pago_si_esta_pendiente(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertTrue(order.can_retry_payment)

    def test_no_puede_reintentar_si_ya_pago(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        mark_as_paid(order)
        order.refresh_from_db()
        self.assertFalse(order.can_retry_payment)

    def test_despacho_gratis_se_muestra_como_texto(self):
        order = create_order_from_cart(cart=self.build_cart(quantity=8), data=VALID_CHECKOUT)
        self.assertEqual(order.shipping_cost_formatted, 'Gratis')

    def test_total_de_unidades(self):
        order = create_order_from_cart(cart=self.build_cart(quantity=3), data=VALID_CHECKOUT)
        self.assertEqual(order.total_units, 3)

    def test_url_absoluta_usa_el_numero_de_orden(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertIn(order.order_number, order.get_absolute_url())


# ===========================================================================
# Creación de órdenes
# ===========================================================================
class CreateOrderTests(OrderTestCase):
    def test_se_crea_la_orden_con_sus_lineas(self):
        order = create_order_from_cart(cart=self.build_cart(2), data=VALID_CHECKOUT)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, 2)

    def test_carrito_vacio_no_crea_orden(self):
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))
        request.session = self.client.session
        with self.assertRaises(OrderError):
            create_order_from_cart(cart=Cart(request), data=VALID_CHECKOUT)

    def test_importes_se_calculan_en_el_servidor(self):
        order = create_order_from_cart(cart=self.build_cart(2), data=VALID_CHECKOUT)
        self.assertEqual(order.subtotal, 20000)
        self.assertEqual(order.total, order.subtotal + order.shipping_cost)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_despacho_se_cobra_bajo_el_umbral(self):
        order = create_order_from_cart(cart=self.build_cart(2), data=VALID_CHECKOUT)
        self.assertEqual(order.shipping_cost, 4990)
        self.assertEqual(order.total, 24990)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_despacho_gratis_sobre_el_umbral(self):
        order = create_order_from_cart(cart=self.build_cart(7), data=VALID_CHECKOUT)
        self.assertEqual(order.shipping_cost, 0)
        self.assertEqual(order.total, 70000)

    def test_lineas_guardan_copia_del_producto(self):
        order = create_order_from_cart(cart=self.build_cart(1), data=VALID_CHECKOUT)
        item = order.items.first()
        self.assertEqual(item.product_name, 'Polera Test')
        self.assertEqual(item.size, 'M')
        self.assertEqual(item.color, 'Negro')
        self.assertEqual(item.unit_price, 10000)

    def test_snapshot_sobrevive_al_cambio_de_precio(self):
        order = create_order_from_cart(cart=self.build_cart(1), data=VALID_CHECKOUT)
        Product.objects.filter(pk=self.product.pk).update(price=99999, name='Otro')
        item = order.items.first()
        self.assertEqual(item.unit_price, 10000)
        self.assertEqual(item.product_name, 'Polera Test')
        Product.objects.filter(pk=self.product.pk).update(
            price=10000, name='Polera Test',
        )

    def test_snapshot_sobrevive_al_borrado_del_producto(self):
        order = create_order_from_cart(cart=self.build_cart(1), data=VALID_CHECKOUT)
        pk = self.product.pk
        ProductVariant.objects.filter(product_id=pk).delete()
        Product.objects.filter(pk=pk).delete()
        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.product_name, 'Polera Test')
        self.assertIsNone(item.product_id)

    def test_orden_de_invitado_no_tiene_usuario(self):
        order = create_order_from_cart(cart=self.build_cart(), data=VALID_CHECKOUT)
        self.assertIsNone(order.user_id)

    def test_orden_de_usuario_autenticado_queda_asociada(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        order = create_order_from_cart(
            cart=self.build_cart(), data=VALID_CHECKOUT, user=user,
        )
        self.assertEqual(order.user_id, user.pk)

    def test_stock_insuficiente_impide_crear_la_orden(self):
        cart = self.build_cart(5)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=2)
        with self.assertRaises(InsufficientStockError):
            create_order_from_cart(cart=cart, data=VALID_CHECKOUT)
        self.assertEqual(Order.objects.count(), 0)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=10)

    def test_error_de_stock_lista_los_problemas(self):
        cart = self.build_cart(5)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=1)
        with self.assertRaises(InsufficientStockError) as ctx:
            create_order_from_cart(cart=cart, data=VALID_CHECKOUT)
        self.assertEqual(len(ctx.exception.issues), 1)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=10)


# ===========================================================================
# Inventario
# ===========================================================================
class StockReservationTests(OrderTestCase):
    def test_crear_orden_reserva_stock(self):
        create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        self.assertEqual(self.refresh_variant().reserved, 3)

    def test_reserva_no_toca_el_stock_fisico(self):
        create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        self.assertEqual(self.refresh_variant().stock, 10)

    def test_reserva_reduce_lo_disponible(self):
        create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        self.assertEqual(self.refresh_variant().available_stock, 7)

    def test_liberar_stock_devuelve_lo_reservado(self):
        order = create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        release_stock(order)
        self.assertEqual(self.refresh_variant().reserved, 0)

    def test_liberar_dos_veces_es_idempotente(self):
        order = create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        self.assertTrue(release_stock(order))
        self.assertFalse(release_stock(order))
        self.assertEqual(self.refresh_variant().reserved, 0)

    def test_confirmar_stock_descuenta_del_fisico(self):
        order = create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        commit_stock(order)
        variant = self.refresh_variant()
        self.assertEqual(variant.stock, 7)
        self.assertEqual(variant.reserved, 0)

    def test_confirmar_stock_dos_veces_no_descuenta_doble(self):
        order = create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        self.assertTrue(commit_stock(order))
        self.assertFalse(commit_stock(order))
        self.assertEqual(self.refresh_variant().stock, 7)

    def test_confirmar_stock_incrementa_las_ventas(self):
        order = create_order_from_cart(cart=self.build_cart(4), data=VALID_CHECKOUT)
        commit_stock(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.sales_count, 4)
        Product.objects.filter(pk=self.product.pk).update(sales_count=0)

    def test_no_se_libera_stock_ya_descontado(self):
        order = create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        commit_stock(order)
        self.assertFalse(release_stock(order))
        self.assertEqual(self.refresh_variant().stock, 7)

    def test_dos_ordenes_reservan_de_forma_acumulativa(self):
        create_order_from_cart(cart=self.build_cart(3), data=VALID_CHECKOUT)
        otro_cliente = self.client_class()
        request = type('Request', (), {})()
        otro_cliente.get(reverse('store:home'))
        request.session = otro_cliente.session
        cart = Cart(request)
        cart.add(self.variant.pk, 4)
        create_order_from_cart(cart=cart, data=VALID_CHECKOUT)
        self.assertEqual(self.refresh_variant().reserved, 7)

    def test_no_se_puede_reservar_mas_alla_del_stock(self):
        """El último producto no puede venderse dos veces."""
        create_order_from_cart(cart=self.build_cart(10), data=VALID_CHECKOUT)

        otro_cliente = self.client_class()
        request = type('Request', (), {})()
        otro_cliente.get(reverse('store:home'))
        request.session = otro_cliente.session
        cart = Cart(request)
        # El segundo comprador ya no puede ni siquiera llenar el carrito.
        from cart.cart import CartError
        with self.assertRaises(CartError):
            cart.add(self.variant.pk, 1)


class OrderStateTransitionTests(OrderTestCase):
    def make_order(self, quantity=3):
        return create_order_from_cart(
            cart=self.build_cart(quantity), data=VALID_CHECKOUT,
        )

    def test_marcar_como_pagada(self):
        order = self.make_order()
        self.assertTrue(mark_as_paid(order))
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)
        self.assertIsNotNone(order.paid_at)

    def test_marcar_como_pagada_descuenta_stock(self):
        order = self.make_order()
        mark_as_paid(order)
        variant = self.refresh_variant()
        self.assertEqual(variant.stock, 7)
        self.assertEqual(variant.reserved, 0)

    def test_marcar_como_pagada_dos_veces_es_idempotente(self):
        order = self.make_order()
        self.assertTrue(mark_as_paid(order))
        self.assertFalse(mark_as_paid(order))
        self.assertEqual(self.refresh_variant().stock, 7)

    def test_marcar_como_rechazada_libera_stock(self):
        order = self.make_order()
        mark_as_rejected(order)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)
        self.assertEqual(self.refresh_variant().reserved, 0)

    def test_rechazar_dos_veces_es_idempotente(self):
        order = self.make_order()
        self.assertTrue(mark_as_rejected(order))
        self.assertFalse(mark_as_rejected(order))

    def test_no_se_puede_rechazar_una_orden_pagada(self):
        order = self.make_order()
        mark_as_paid(order)
        self.assertFalse(mark_as_rejected(order))
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAID)

    def test_cancelar_libera_stock(self):
        order = self.make_order()
        mark_as_cancelled(order)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.refresh_variant().reserved, 0)

    def test_no_se_puede_cancelar_una_orden_pagada(self):
        order = self.make_order()
        mark_as_paid(order)
        self.assertFalse(mark_as_cancelled(order))

    def test_pagar_tras_rechazo_sigue_funcionando(self):
        order = self.make_order()
        mark_as_rejected(order)
        order.refresh_from_db()
        # El stock se liberó; se vuelve a reservar al reintentar.
        self.assertEqual(self.refresh_variant().reserved, 0)


# ===========================================================================
# Regiones y formulario
# ===========================================================================
class RegionsTests(TestCase):
    def test_hay_dieciseis_regiones(self):
        self.assertEqual(len(REGIONS), 16)

    def test_todas_las_regiones_tienen_comunas(self):
        for region, communes in REGIONS.items():
            with self.subTest(region=region):
                self.assertGreater(len(communes), 0)

    def test_comunas_de_una_region_conocida(self):
        self.assertIn('Providencia', communes_for('Metropolitana de Santiago'))

    def test_region_inexistente_devuelve_lista_vacia(self):
        self.assertEqual(communes_for('Narnia'), [])

    def test_validacion_de_comuna_correcta(self):
        self.assertTrue(is_valid_location('Metropolitana de Santiago', 'Ñuñoa'))

    def test_validacion_rechaza_comuna_de_otra_region(self):
        self.assertFalse(is_valid_location('Metropolitana de Santiago', 'Arica'))

    def test_validacion_rechaza_comuna_inventada(self):
        self.assertFalse(is_valid_location('Metropolitana de Santiago', 'Hackerville'))

    def test_sin_comunas_duplicadas_en_una_region(self):
        for region, communes in REGIONS.items():
            with self.subTest(region=region):
                self.assertEqual(len(communes), len(set(communes)))


class CheckoutFormTests(TestCase):
    def test_formulario_valido(self):
        self.assertTrue(CheckoutForm(data=VALID_CHECKOUT).is_valid())

    def test_falta_nombre(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'first_name': ''})
        self.assertIn('first_name', form.errors)

    def test_email_invalido(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'email': 'no-es-email'})
        self.assertIn('email', form.errors)

    def test_email_se_normaliza_a_minusculas(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'email': 'ANA@TEST.CL'})
        form.is_valid()
        self.assertEqual(form.cleaned_data['email'], 'ana@test.cl')

    def test_telefono_con_espacios_se_acepta(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'phone': '+56 9 1234 5678'})
        self.assertTrue(form.is_valid())

    def test_telefono_con_guiones_se_acepta(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'phone': '9-1234-5678'})
        self.assertTrue(form.is_valid())

    def test_telefono_con_letras_se_rechaza(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'phone': 'llamame'})
        self.assertIn('phone', form.errors)

    def test_telefono_demasiado_corto_se_rechaza(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'phone': '123'})
        self.assertIn('phone', form.errors)

    def test_comuna_de_otra_region_se_rechaza(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'commune': 'Arica'})
        self.assertIn('commune', form.errors)

    def test_region_inventada_se_rechaza(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'region': 'Narnia'})
        self.assertIn('region', form.errors)

    def test_informacion_adicional_es_opcional(self):
        form = CheckoutForm(data={**VALID_CHECKOUT, 'extra': ''})
        self.assertTrue(form.is_valid())


# ===========================================================================
# Vistas
# ===========================================================================
class CheckoutViewTests(OrderTestCase):
    def test_checkout_con_carrito_vacio_redirige(self):
        response = self.client.get(reverse('orders:checkout'))
        self.assertRedirects(response, reverse('store:product_list'))

    def test_checkout_con_carrito_muestra_formulario(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        response = self.client.get(reverse('orders:checkout'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Finalizar compra')

    def test_checkout_valido_crea_orden_y_redirige_al_pago(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        response = self.client.post(reverse('orders:checkout'), VALID_CHECKOUT)
        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse('payments:start', args=[order.order_number]),
            fetch_redirect_response=False,
        )

    def test_checkout_valido_vacia_el_carrito(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), VALID_CHECKOUT)
        estado = self.client.get(reverse('cart:state')).json()
        self.assertEqual(estado['cart']['count'], 0)

    def test_checkout_invalido_no_crea_orden(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), {
            **VALID_CHECKOUT, 'email': 'malo',
        })
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_invalido_conserva_el_carrito(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), {
            **VALID_CHECKOUT, 'email': 'malo',
        })
        estado = self.client.get(reverse('cart:state')).json()
        self.assertEqual(estado['cart']['count'], 2)

    def test_checkout_requiere_csrf(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        cliente.post(reverse('cart:add'), {'variant_id': self.variant.pk})
        response = cliente.post(reverse('orders:checkout'), VALID_CHECKOUT)
        self.assertEqual(response.status_code, 403)

    def test_no_se_puede_manipular_el_total_desde_el_post(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.client.post(reverse('orders:checkout'), {
            **VALID_CHECKOUT, 'total': 1, 'subtotal': 1, 'shipping_cost': 0,
        })
        order = Order.objects.get()
        self.assertEqual(order.subtotal, 20000)

    def test_api_de_comunas(self):
        response = self.client.get(reverse('orders:communes_api'), {
            'region': 'Metropolitana de Santiago',
        })
        self.assertIn('Providencia', response.json()['communes'])

    def test_api_de_comunas_con_region_invalida(self):
        response = self.client.get(reverse('orders:communes_api'), {'region': 'X'})
        self.assertEqual(response.json()['communes'], [])


class OrderAccessControlTests(OrderTestCase):
    """El control de acceso a órdenes ajenas es crítico."""

    def setUp(self):
        self.ana = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.beto = User.objects.create_user('beto', 'beto@test.cl', 'ClaveSegura123')
        self.orden_de_ana = create_order_from_cart(
            cart=self.build_cart(1), data=VALID_CHECKOUT, user=self.ana,
        )

    def test_el_dueno_ve_su_orden(self):
        self.client.login(username='ana', password='ClaveSegura123')
        response = self.client.get(self.orden_de_ana.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_otro_usuario_no_ve_la_orden(self):
        self.client.login(username='beto', password='ClaveSegura123')
        response = self.client.get(self.orden_de_ana.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_anonimo_no_ve_orden_de_usuario_registrado(self):
        response = self.client.get(self.orden_de_ana.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_el_staff_puede_ver_cualquier_orden(self):
        staff = User.objects.create_user(
            'admin2', 'admin2@test.cl', 'ClaveSegura123', is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self.orden_de_ana.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_orden_inexistente_devuelve_404(self):
        self.client.login(username='ana', password='ClaveSegura123')
        response = self.client.get(reverse('orders:detail', args=['GF00000000AAAA']))
        self.assertEqual(response.status_code, 404)

    def test_invitado_ve_su_orden_gracias_a_la_sesion(self):
        cliente = self.client_class()
        cliente.get(reverse('store:home'))
        cliente.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 1,
        })
        cliente.post(reverse('orders:checkout'), VALID_CHECKOUT)
        order = Order.objects.filter(user__isnull=True).latest('created_at')
        response = cliente.get(order.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_otro_invitado_no_ve_la_orden(self):
        cliente = self.client_class()
        cliente.get(reverse('store:home'))
        cliente.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 1,
        })
        cliente.post(reverse('orders:checkout'), VALID_CHECKOUT)
        order = Order.objects.filter(user__isnull=True).latest('created_at')

        intruso = self.client_class()
        response = intruso.get(order.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_historial_requiere_autenticacion(self):
        response = self.client.get(reverse('orders:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cuenta/login/', response['Location'])

    def test_historial_solo_muestra_ordenes_propias(self):
        self.client.login(username='beto', password='ClaveSegura123')
        response = self.client.get(reverse('orders:list'))
        self.assertNotContains(response, self.orden_de_ana.order_number)

    def test_historial_muestra_las_ordenes_del_usuario(self):
        self.client.login(username='ana', password='ClaveSegura123')
        response = self.client.get(reverse('orders:list'))
        self.assertContains(response, self.orden_de_ana.order_number)
