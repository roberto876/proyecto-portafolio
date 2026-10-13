"""Pruebas de los correos de compra y de los enlaces firmados de acceso."""
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.cart import Cart
from orders.access import has_signed_access, sign_order_access
from orders.emails import send_order_paid_emails
from orders.models import Order
from orders.services import create_order_from_cart, mark_as_paid, mark_as_rejected
from payments.tests import CHECKOUT
from store.models import Category, Product, ProductVariant, Size, StoreSettings


@override_settings(SITE_URL='https://tienda.test')
class OrderEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(category=category, name='Polera Mail', price=15000)
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.L, color='Negro', stock=10,
        )

    def setUp(self):
        store = StoreSettings.load()
        store.store_name = 'Fuerza Sur'
        store.contact_email = 'ventas@fuerzasur.cl'
        store.save()

    def make_order(self):
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))
        request.session = self.client.session
        cart = Cart(request)
        cart.add(self.variant.pk, 2)
        return create_order_from_cart(cart=cart, data=CHECKOUT)

    def pay(self, order):
        with self.captureOnCommitCallbacks(execute=True):
            mark_as_paid(order)

    def test_pagar_envia_confirmacion_al_cliente_y_aviso_a_la_tienda(self):
        self.pay(self.make_order())
        recipients = sorted(address for message in mail.outbox for address in message.to)
        self.assertEqual(recipients, ['ana@test.cl', 'ventas@fuerzasur.cl'])

    def test_confirmacion_incluye_el_detalle_de_la_compra(self):
        order = self.make_order()
        self.pay(order)
        confirmation = next(m for m in mail.outbox if 'ana@test.cl' in m.to)
        self.assertIn(order.order_number, confirmation.subject)
        self.assertIn('Fuerza Sur', confirmation.subject)
        self.assertIn('Polera Mail', confirmation.body)
        self.assertIn(order.total_formatted, confirmation.body)

    def test_confirmacion_trae_version_html(self):
        self.pay(self.make_order())
        confirmation = next(m for m in mail.outbox if 'ana@test.cl' in m.to)
        html, mimetype = confirmation.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('Ver mi pedido', html)

    def test_responder_la_confirmacion_llega_a_la_tienda(self):
        self.pay(self.make_order())
        confirmation = next(m for m in mail.outbox if 'ana@test.cl' in m.to)
        self.assertEqual(confirmation.reply_to, ['ventas@fuerzasur.cl'])

    def test_aviso_a_la_tienda_incluye_datos_de_despacho(self):
        order = self.make_order()
        self.pay(order)
        notice = next(m for m in mail.outbox if 'ventas@fuerzasur.cl' in m.to)
        self.assertIn(order.full_shipping_address, notice.body)
        self.assertIn('/admin/orders/order/', notice.body)

    def test_sin_email_de_tienda_solo_se_avisa_al_cliente(self):
        StoreSettings.objects.update(contact_email='')
        self.pay(self.make_order())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ana@test.cl'])

    def test_pago_duplicado_no_reenvia_correos(self):
        order = self.make_order()
        self.pay(order)
        self.pay(order)
        self.assertEqual(len(mail.outbox), 2)

    def test_pago_rechazado_no_envia_correos(self):
        with self.captureOnCommitCallbacks(execute=True):
            mark_as_rejected(self.make_order())
        self.assertEqual(len(mail.outbox), 0)

    def test_fallo_de_correo_no_rompe_el_pago(self):
        order = self.make_order()
        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('SMTP caído')):
            self.pay(order)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)

    def test_orden_inexistente_no_rompe(self):
        send_order_paid_emails(999999)
        self.assertEqual(len(mail.outbox), 0)

    def test_enlace_del_correo_abre_la_orden_en_otro_dispositivo(self):
        order = self.make_order()
        self.pay(order)
        confirmation = next(m for m in mail.outbox if 'ana@test.cl' in m.to)
        link = next(line for line in confirmation.body.splitlines() if 'acceso=' in line)
        self.assertTrue(link.startswith('https://tienda.test/'))

        otro_dispositivo = self.client_class()
        response = otro_dispositivo.get(link.replace('https://tienda.test', ''))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)


class SignedAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        product = Product.objects.create(category=category, name='Polera', price=15000)
        cls.variant = ProductVariant.objects.create(
            product=product, size=Size.L, color='Negro', stock=10,
        )

    def make_order(self):
        request = type('Request', (), {})()
        client = self.client_class()
        client.get(reverse('store:home'))
        request.session = client.session
        cart = Cart(request)
        cart.add(self.variant.pk, 1)
        return create_order_from_cart(cart=cart, data=CHECKOUT)

    def test_firma_valida(self):
        order = self.make_order()
        self.assertTrue(has_signed_access(sign_order_access(order), order))

    def test_firma_de_otra_orden_no_sirve(self):
        order, other = self.make_order(), self.make_order()
        self.assertFalse(has_signed_access(sign_order_access(other), order))

    def test_firma_vacia_o_basura(self):
        order = self.make_order()
        self.assertFalse(has_signed_access('', order))
        self.assertFalse(has_signed_access('basura', order))

    @override_settings(PAYMENT_ACCESS_MAX_AGE=-1)
    def test_firma_vencida(self):
        order = self.make_order()
        self.assertFalse(has_signed_access(sign_order_access(order), order))

    def test_detalle_de_orden_acepta_la_firma(self):
        order = self.make_order()
        response = self.client_class().get(
            order.get_absolute_url(), {'acceso': sign_order_access(order)},
        )
        self.assertEqual(response.status_code, 200)

    def test_detalle_de_orden_rechaza_firma_falsa(self):
        order = self.make_order()
        response = self.client_class().get(order.get_absolute_url(), {'acceso': 'x'})
        self.assertEqual(response.status_code, 404)

    def test_orden_de_usuario_registrado_con_firma(self):
        """El enlace del correo también sirve a clientes con cuenta."""
        from django.contrib.auth.models import User
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        order = self.make_order()
        Order.objects.filter(pk=order.pk).update(user=user)
        response = self.client_class().get(
            order.get_absolute_url(), {'acceso': sign_order_access(order)},
        )
        self.assertEqual(response.status_code, 200)
