"""Pruebas del carrito: cálculo de importes, validación de stock y seguridad."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.cart import Cart, CartError
from store.models import Category, Product, ProductVariant, Size


class CartTestCase(TestCase):
    """Base con un catálogo mínimo y utilidades de sesión."""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=cls.category, name='Polera Test', price=10000,
            main_image='https://example.test/a.jpg',
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=10,
        )
        cls.otro = Product.objects.create(
            category=cls.category, name='Short Test', price=25000,
        )
        cls.variante_otro = ProductVariant.objects.create(
            product=cls.otro, size=Size.L, color='Azul', stock=4,
        )

    def make_cart(self):
        """Construye un carrito apoyado en la sesión del cliente de pruebas."""
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))  # Inicializa la sesión.
        request.session = self.client.session
        return Cart(request)

    def persist(self, cart):
        """Guarda en el cliente la sesión modificada por el carrito."""
        cart.session.save()
        self.client.cookies['sessionid'] = cart.session.session_key


# ===========================================================================
# Operaciones básicas
# ===========================================================================
class CartOperationsTests(CartTestCase):
    def test_carrito_nuevo_esta_vacio(self):
        cart = self.make_cart()
        self.assertTrue(cart.is_empty)
        self.assertEqual(len(cart), 0)

    def test_agregar_producto(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        self.assertEqual(len(cart), 2)
        self.assertEqual(cart.distinct_count, 1)

    def test_agregar_dos_veces_suma_cantidades(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        cart.add(self.variant.pk, 3)
        self.assertEqual(len(cart), 5)

    def test_override_reemplaza_la_cantidad(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 5)
        cart.add(self.variant.pk, 2, override=True)
        self.assertEqual(len(cart), 2)

    def test_actualizar_cantidad(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        cart.update(self.variant.pk, 4)
        self.assertEqual(len(cart), 4)

    def test_actualizar_producto_ausente_falla(self):
        cart = self.make_cart()
        with self.assertRaises(CartError):
            cart.update(self.variant.pk, 3)

    def test_eliminar_producto(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        self.assertTrue(cart.remove(self.variant.pk))
        self.assertTrue(cart.is_empty)

    def test_eliminar_producto_ausente_devuelve_false(self):
        self.assertFalse(self.make_cart().remove(999))

    def test_vaciar_carrito(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        cart.add(self.variante_otro.pk, 1)
        cart.clear()
        self.assertTrue(cart.is_empty)

    def test_multiples_lineas(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        cart.add(self.variante_otro.pk, 1)
        self.assertEqual(cart.distinct_count, 2)
        self.assertEqual(len(cart), 3)

    def test_iteracion_devuelve_lineas(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        self.assertEqual(len(list(cart)), 1)


# ===========================================================================
# Validación de entrada
# ===========================================================================
class CartValidationTests(CartTestCase):
    def test_cantidad_cero_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 0)

    def test_cantidad_negativa_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, -5)

    def test_cantidad_no_numerica_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 'muchos')

    def test_cantidad_nula_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, None)

    def test_cantidad_decimal_como_texto_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, '2.5')

    def test_guion_bajo_no_se_interpreta_como_numero(self):
        """`int('1_0')` vale 10 en Python: el navegador nunca envía eso."""
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, '1_0')

    def test_espacios_alrededor_de_la_cantidad_se_toleran(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, ' 3 ')
        self.assertEqual(len(cart), 3)

    @override_settings(CART_MAX_QUANTITY_PER_ITEM=10)
    def test_agregar_cuando_ya_esta_en_el_maximo_avisa(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 10)
        with self.assertRaisesMessage(CartError, 'máximo de 10'):
            cart.add(self.variant.pk, 1)
        self.assertEqual(len(cart), 10)

    @override_settings(CART_MAX_QUANTITY_PER_ITEM=10)
    def test_cantidad_sobre_el_tope_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 11)

    def test_variante_inexistente_rechazada(self):
        with self.assertRaises(CartError):
            self.make_cart().add(999999, 1)

    def test_id_no_numerico_rechazado(self):
        with self.assertRaises(CartError):
            self.make_cart().add('abc', 1)

    def test_id_nulo_rechazado(self):
        with self.assertRaises(CartError):
            self.make_cart().add(None, 1)

    def test_variante_inactiva_rechazada(self):
        self.variant.is_active = False
        self.variant.save(update_fields=['is_active'])
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 1)
        self.variant.is_active = True
        self.variant.save(update_fields=['is_active'])

    def test_producto_inactivo_rechazado(self):
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 1)
        self.product.is_active = True
        self.product.save(update_fields=['is_active'])

    @override_settings(CART_MAX_DISTINCT_ITEMS=1)
    def test_tope_de_lineas_distintas(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        with self.assertRaises(CartError):
            cart.add(self.variante_otro.pk, 1)


# ===========================================================================
# Stock
# ===========================================================================
class CartStockTests(CartTestCase):
    def test_no_se_puede_agregar_mas_del_stock(self):
        with self.assertRaises(CartError):
            self.make_cart().add(self.variante_otro.pk, 5)  # stock = 4

    def test_se_puede_agregar_exactamente_el_stock(self):
        cart = self.make_cart()
        cart.add(self.variante_otro.pk, 4)
        self.assertEqual(len(cart), 4)

    def test_variante_agotada_rechazada(self):
        self.variant.stock = 0
        self.variant.save(update_fields=['stock'])
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 1)
        self.variant.stock = 10
        self.variant.save(update_fields=['stock'])

    def test_stock_reservado_no_es_vendible(self):
        self.variant.reserved = 9
        self.variant.save(update_fields=['reserved'])
        with self.assertRaises(CartError):
            self.make_cart().add(self.variant.pk, 2)
        self.variant.reserved = 0
        self.variant.save(update_fields=['reserved'])

    def test_stock_issues_detecta_agotado_posterior(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 5)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=0)
        cart._items = None  # Fuerza la relectura desde la base de datos.
        self.assertEqual(len(cart.stock_issues()), 1)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=10)

    def test_stock_issues_detecta_stock_insuficiente(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 8)
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=3)
        cart._items = None
        self.assertIn('3', cart.stock_issues()[0])
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock=10)

    def test_carrito_sin_problemas_es_comprable(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        self.assertTrue(cart.is_purchasable)

    def test_carrito_vacio_no_es_comprable(self):
        self.assertFalse(self.make_cart().is_purchasable)

    def test_linea_eliminada_del_catalogo_desaparece(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        variant_pk = self.variant.pk
        ProductVariant.objects.filter(pk=variant_pk).delete()
        cart._items = None
        self.assertTrue(cart.is_empty)
        # Restaura la variante para el resto de la clase.
        ProductVariant.objects.create(
            pk=variant_pk, product=self.product, size=Size.M,
            color='Negro', stock=10,
        )


# ===========================================================================
# Importes
# ===========================================================================
class CartTotalsTests(CartTestCase):
    def test_subtotal_de_una_linea(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 3)
        self.assertEqual(cart.subtotal, 30000)

    def test_subtotal_de_varias_lineas(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)      # 20.000
        cart.add(self.variante_otro.pk, 1)  # 25.000
        self.assertEqual(cart.subtotal, 45000)

    def test_subtotal_de_carrito_vacio(self):
        self.assertEqual(self.make_cart().subtotal, 0)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_despacho_se_cobra_bajo_el_umbral(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)  # 10.000
        self.assertEqual(cart.shipping_cost, 4990)
        self.assertFalse(cart.has_free_shipping)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_despacho_gratis_sobre_el_umbral(self):
        cart = self.make_cart()
        cart.add(self.variante_otro.pk, 3)  # 75.000
        self.assertEqual(cart.shipping_cost, 0)
        self.assertTrue(cart.has_free_shipping)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_despacho_gratis_justo_en_el_umbral(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 6)  # exactamente 60.000
        self.assertTrue(cart.has_free_shipping)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000)
    def test_falta_para_envio_gratis(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        self.assertEqual(cart.amount_for_free_shipping, 50000)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000)
    def test_falta_para_envio_gratis_es_cero_si_ya_aplica(self):
        cart = self.make_cart()
        cart.add(self.variante_otro.pk, 3)
        self.assertEqual(cart.amount_for_free_shipping, 0)

    def test_carrito_vacio_no_cobra_despacho(self):
        self.assertEqual(self.make_cart().shipping_cost, 0)

    @override_settings(FREE_SHIPPING_THRESHOLD=60000, SHIPPING_COST=4990)
    def test_total_suma_subtotal_y_despacho(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        self.assertEqual(cart.total, 14990)

    def test_precio_se_lee_de_la_base_de_datos(self):
        """El precio del carrito debe seguir al catálogo, no a la sesión."""
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        Product.objects.filter(pk=self.product.pk).update(price=99999)
        cart._items = None
        self.assertEqual(cart.subtotal, 99999)
        Product.objects.filter(pk=self.product.pk).update(price=10000)

    def test_serializacion_incluye_totales(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 2)
        data = cart.to_dict()
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['subtotal'], 20000)
        self.assertIn('total_formatted', data)

    def test_serializacion_de_linea(self):
        cart = self.make_cart()
        cart.add(self.variant.pk, 1)
        item = cart.to_dict()['items'][0]
        self.assertEqual(item['name'], 'Polera Test')
        self.assertEqual(item['size'], 'M')
        self.assertEqual(item['color'], 'Negro')


# ===========================================================================
# Vistas HTTP
# ===========================================================================
class CartViewTests(CartTestCase):
    def test_pagina_del_carrito_responde(self):
        response = self.client.get(reverse('cart:detail'))
        self.assertEqual(response.status_code, 200)

    def test_carrito_vacio_muestra_estado_vacio(self):
        response = self.client.get(reverse('cart:detail'))
        self.assertContains(response, 'carrito está vacío')

    def test_agregar_por_post_redirige(self):
        response = self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        self.assertRedirects(response, reverse('cart:detail'))

    def test_agregar_por_ajax_devuelve_json(self):
        response = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 2},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['cart']['count'], 2)

    def test_agregar_get_no_permitido(self):
        response = self.client.get(reverse('cart:add'))
        self.assertEqual(response.status_code, 405)

    def test_actualizar_get_no_permitido(self):
        self.assertEqual(self.client.get(reverse('cart:update')).status_code, 405)

    def test_eliminar_get_no_permitido(self):
        self.assertEqual(self.client.get(reverse('cart:remove')).status_code, 405)

    def test_vaciar_get_no_permitido(self):
        self.assertEqual(self.client.get(reverse('cart:clear')).status_code, 405)

    def test_agregar_con_stock_insuficiente_devuelve_400(self):
        response = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variante_otro.pk, 'quantity': 99},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    def test_flujo_completo_agregar_actualizar_eliminar(self):
        add = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 3},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(add.json()['cart']['count'], 3)

        update = self.client.post(
            reverse('cart:update'),
            {'variant_id': self.variant.pk, 'quantity': 1},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(update.json()['cart']['count'], 1)

        remove = self.client.post(
            reverse('cart:remove'),
            {'variant_id': self.variant.pk},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(remove.json()['cart']['count'], 0)

    def test_estado_del_carrito_es_publico(self):
        response = self.client.get(reverse('cart:state'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('cart', response.json())

    def test_carrito_persiste_entre_peticiones(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        response = self.client.get(reverse('cart:detail'))
        self.assertContains(response, 'Polera Test')

    def test_carrito_es_independiente_por_sesion(self):
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        otro_cliente = self.client_class()
        response = otro_cliente.get(reverse('cart:state'))
        self.assertEqual(response.json()['cart']['count'], 0)


class CartSecurityTests(CartTestCase):
    def test_csrf_es_obligatorio_al_agregar(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        response = cliente.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 1,
        })
        self.assertEqual(response.status_code, 403)

    def test_csrf_es_obligatorio_al_eliminar(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        response = cliente.post(reverse('cart:remove'), {
            'variant_id': self.variant.pk,
        })
        self.assertEqual(response.status_code, 403)

    def test_csrf_es_obligatorio_al_vaciar(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        self.assertEqual(cliente.post(reverse('cart:clear')).status_code, 403)

    def test_no_se_puede_inyectar_precio(self):
        """Enviar un precio en el POST no debe alterar el importe cobrado."""
        response = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 1, 'price': 1},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(response.json()['cart']['subtotal'], 10000)

    def test_no_se_puede_inyectar_subtotal(self):
        response = self.client.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 2, 'subtotal': 5},
            headers={'x-requested-with': 'XMLHttpRequest'},
        )
        self.assertEqual(response.json()['cart']['subtotal'], 20000)

    def test_sesion_corrupta_no_rompe_el_carrito(self):
        session = self.client.session
        session['cart'] = 'esto-no-es-un-dict'
        session.save()
        response = self.client.get(reverse('cart:detail'))
        self.assertEqual(response.status_code, 200)

    def test_sesion_con_ids_invalidos_se_limpia(self):
        session = self.client.session
        session['cart'] = {'no-numerico': 3, '999999': 2}
        session.save()
        response = self.client.get(reverse('cart:state'))
        self.assertEqual(response.json()['cart']['count'], 0)


class CartAuthenticatedTests(CartTestCase):
    def test_usuario_autenticado_tiene_su_propio_carrito(self):
        User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('cart:add'), {
            'variant_id': self.variant.pk, 'quantity': 2,
        })
        response = self.client.get(reverse('cart:state'))
        self.assertEqual(response.json()['cart']['count'], 2)
