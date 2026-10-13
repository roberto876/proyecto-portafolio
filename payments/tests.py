"""Pruebas del flujo de pago con Webpay Plus.

Ninguna prueba contacta la API real de Transbank: se inyecta un doble de
prueba que implementa el mismo contrato que ``TransbankPaymentService``.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from transbank.common.integration_type import IntegrationType
from transbank.error.transbank_error import TransbankError

from cart.cart import Cart
from orders.models import Order, OrderStatus
from orders.services import create_order_from_cart
from payments.models import PaymentStatus, PaymentTransaction
from payments.services import (
    PaymentError,
    cancel_transaction,
    confirm_transaction,
    expire_transaction,
    start_transaction,
)
from payments.transbank import (
    CreatedTransaction,
    PaymentGatewayError,
    TransbankPaymentService,
    _sanitize,
    _to_result,
)
from store.models import Category, Product, ProductVariant, Size

CHECKOUT = {
    'first_name': 'Ana', 'last_name': 'Soto', 'email': 'ana@test.cl',
    'phone': '+56912345678', 'region': 'Metropolitana de Santiago',
    'commune': 'Providencia', 'address': 'Av. Providencia',
    'address_number': '1234', 'extra': '',
}


def webpay_response(*, amount, buy_order, status='AUTHORIZED', response_code=0):
    """Construye una respuesta con la forma real de la API de Transbank."""
    return {
        'vci': 'TSY',
        'amount': amount,
        'status': status,
        'buy_order': buy_order,
        'session_id': 'sesion-de-prueba',
        'card_detail': {'card_number': '6623'},
        'accounting_date': '0910',
        'transaction_date': '2026-09-10T12:00:00.000Z',
        'authorization_code': '123456',
        'payment_type_code': 'VN',
        'response_code': response_code,
        'installments_number': 0,
    }


class FakeGateway:
    """Doble de prueba de la pasarela de pago."""

    def __init__(self, *, commit_response=None, fail_on_create=False,
                 fail_on_commit=False):
        self.commit_response = commit_response
        self.fail_on_create = fail_on_create
        self.fail_on_commit = fail_on_commit
        self.create_calls = []
        self.commit_calls = []

    def create(self, *, buy_order, session_id, amount, return_url):
        self.create_calls.append({
            'buy_order': buy_order, 'session_id': session_id,
            'amount': amount, 'return_url': return_url,
        })
        if self.fail_on_create:
            raise PaymentGatewayError('Transbank no disponible.')

        # Transbank emite un token distinto por transacción; el doble hace lo
        # mismo para que los reintentos se comporten como en producción.
        suffix = '' if len(self.create_calls) == 1 else f'-{len(self.create_calls)}'
        return CreatedTransaction(
            token=f'token-{buy_order}{suffix}',
            url='https://webpay3gint.transbank.cl/pago',
        )

    def commit(self, token):
        self.commit_calls.append(token)
        if self.fail_on_commit:
            raise PaymentGatewayError('No pudimos confirmar el pago.')
        return _to_result(self.commit_response)

    def status(self, token):
        return _to_result(self.commit_response)


class PaymentTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=cls.category, name='Polera Test', price=10000,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=20,
        )

    def make_order(self, quantity=2, user=None):
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))
        request.session = self.client.session
        cart = Cart(request)
        cart.add(self.variant.pk, quantity)
        return create_order_from_cart(cart=cart, data=CHECKOUT, user=user)

    def approved_gateway(self, order):
        return FakeGateway(commit_response=webpay_response(
            amount=order.total, buy_order=order.order_number,
        ))

    def rejected_gateway(self, order, response_code=-1):
        return FakeGateway(commit_response=webpay_response(
            amount=order.total, buy_order=order.order_number,
            status='FAILED', response_code=response_code,
        ))

    def assert_result_redirect(self, response, name, order):
        """Comprueba la redirección a éxito/fallo con enlace de acceso firmado."""
        self.assertEqual(response.status_code, 302)
        location = response['Location']
        self.assertTrue(
            location.startswith(reverse(name, args=[order.order_number])),
            msg=f'Redirección inesperada: {location}',
        )
        self.assertIn('acceso=', location)


# ===========================================================================
# Capa Transbank
# ===========================================================================
class TransbankServiceTests(TestCase):
    def test_ambiente_de_integracion_usa_test(self):
        service = TransbankPaymentService(environment='integration')
        self.assertEqual(service.integration_type, IntegrationType.TEST)
        self.assertFalse(service.is_production)

    def test_ambiente_de_produccion_usa_live(self):
        service = TransbankPaymentService(environment='production')
        self.assertEqual(service.integration_type, IntegrationType.LIVE)
        self.assertTrue(service.is_production)

    def test_buy_order_vacio_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                '', 'sesion', 1000, 'https://x.cl/r',
            )

    def test_buy_order_demasiado_largo_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'X' * 27, 'sesion', 1000, 'https://x.cl/r',
            )

    def test_session_id_demasiado_largo_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'GF123', 'S' * 62, 1000, 'https://x.cl/r',
            )

    def test_return_url_demasiado_larga_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'GF123', 'sesion', 1000, 'https://x.cl/' + 'a' * 250,
            )

    def test_monto_cero_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'GF123', 'sesion', 0, 'https://x.cl/r',
            )

    def test_monto_negativo_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'GF123', 'sesion', -100, 'https://x.cl/r',
            )

    def test_monto_decimal_se_rechaza(self):
        with self.assertRaises(PaymentGatewayError):
            TransbankPaymentService()._validate_create_params(
                'GF123', 'sesion', 100.5, 'https://x.cl/r',
            )

    def test_parametros_validos_no_lanzan(self):
        TransbankPaymentService()._validate_create_params(
            'GF20260910ABCDEF', 'sesion', 24990, 'https://x.cl/retorno',
        )

    def test_error_del_sdk_se_traduce(self):
        service = TransbankPaymentService()
        with patch.object(service, '_transaction') as fake:
            fake.return_value.create.side_effect = TransbankError('fallo', 422)
            with self.assertRaises(PaymentGatewayError):
                service.create(
                    buy_order='GF123', session_id='s', amount=1000,
                    return_url='https://x.cl/r',
                )

    def test_respuesta_incompleta_se_rechaza(self):
        service = TransbankPaymentService()
        with patch.object(service, '_transaction') as fake:
            fake.return_value.create.return_value = {'token': 'abc'}  # sin url
            with self.assertRaises(PaymentGatewayError):
                service.create(
                    buy_order='GF123', session_id='s', amount=1000,
                    return_url='https://x.cl/r',
                )

    def test_error_de_red_se_traduce(self):
        service = TransbankPaymentService()
        with patch.object(service, '_transaction') as fake:
            fake.return_value.commit.side_effect = ConnectionError('sin red')
            with self.assertRaises(PaymentGatewayError):
                service.commit('token')


class TransactionResultTests(TestCase):
    def test_aprobado_requiere_codigo_cero_y_estado_autorizado(self):
        result = _to_result(webpay_response(amount=1000, buy_order='GF1'))
        self.assertTrue(result.is_approved)

    def test_codigo_distinto_de_cero_no_es_aprobado(self):
        result = _to_result(webpay_response(
            amount=1000, buy_order='GF1', response_code=-1,
        ))
        self.assertFalse(result.is_approved)

    def test_estado_no_autorizado_no_es_aprobado(self):
        """Aunque el código sea 0, si el estado no es AUTHORIZED se rechaza."""
        result = _to_result(webpay_response(
            amount=1000, buy_order='GF1', status='FAILED', response_code=0,
        ))
        self.assertFalse(result.is_approved)

    def test_estado_reversed_no_es_aprobado(self):
        result = _to_result(webpay_response(
            amount=1000, buy_order='GF1', status='REVERSED',
        ))
        self.assertFalse(result.is_approved)

    def test_respuesta_sin_response_code(self):
        payload = webpay_response(amount=1000, buy_order='GF1')
        del payload['response_code']
        result = _to_result(payload)
        self.assertIsNone(result.response_code)
        self.assertFalse(result.is_approved)

    def test_mensaje_para_el_usuario_de_rechazo_conocido(self):
        result = _to_result(webpay_response(
            amount=1000, buy_order='GF1', status='FAILED', response_code=-1,
        ))
        self.assertIn('banco', result.user_message)

    def test_mensaje_para_codigo_desconocido(self):
        result = _to_result(webpay_response(
            amount=1000, buy_order='GF1', status='FAILED', response_code=-99,
        ))
        self.assertTrue(result.user_message)

    def test_solo_se_conservan_los_ultimos_cuatro_digitos(self):
        result = _to_result(webpay_response(amount=1000, buy_order='GF1'))
        self.assertEqual(result.card_last_digits, '6623')


class SanitizeTests(TestCase):
    def test_se_elimina_el_detalle_de_la_tarjeta(self):
        clean = _sanitize(webpay_response(amount=1000, buy_order='GF1'))
        self.assertNotIn('card_detail', clean)

    def test_se_conservan_los_ultimos_digitos(self):
        clean = _sanitize(webpay_response(amount=1000, buy_order='GF1'))
        self.assertEqual(clean['card_last_digits'], '6623')

    def test_nunca_se_guarda_un_numero_completo(self):
        payload = webpay_response(amount=1000, buy_order='GF1')
        payload['card_detail'] = {'card_number': '4051885600446623'}
        clean = _sanitize(payload)
        self.assertEqual(clean['card_last_digits'], '6623')
        self.assertNotIn('4051885600446623', str(clean))

    def test_no_se_guardan_campos_de_cvv(self):
        clean = _sanitize(webpay_response(amount=1000, buy_order='GF1'))
        self.assertNotIn('cvv', str(clean).lower())


# ===========================================================================
# Inicio de la transacción
# ===========================================================================
class StartTransactionTests(PaymentTestCase):
    def test_se_crea_la_transaccion_local(self):
        order = self.make_order()
        gateway = self.approved_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)

        payment = PaymentTransaction.objects.get()
        self.assertEqual(payment.order_id, order.pk)
        self.assertEqual(payment.status, PaymentStatus.CREATED)
        self.assertEqual(payment.amount, order.total)

    def test_el_monto_enviado_es_el_de_la_orden(self):
        order = self.make_order()
        gateway = self.approved_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        self.assertEqual(gateway.create_calls[0]['amount'], order.total)

    def test_el_buy_order_es_el_numero_de_orden(self):
        order = self.make_order()
        gateway = self.approved_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        self.assertEqual(gateway.create_calls[0]['buy_order'], order.order_number)

    def test_el_session_id_no_es_la_sesion_de_django(self):
        order = self.make_order()
        gateway = self.approved_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        enviado = gateway.create_calls[0]['session_id']
        self.assertNotEqual(enviado, self.client.session.session_key)
        self.assertIn(order.order_number, enviado)

    def test_no_se_puede_pagar_una_orden_ya_pagada(self):
        order = self.make_order()
        gateway = self.approved_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        confirm_transaction('token-' + order.order_number, gateway=gateway)

        order.refresh_from_db()
        with self.assertRaises(PaymentError):
            start_transaction(order, return_url='https://x.cl/r', gateway=gateway)

    def test_no_se_puede_pagar_una_orden_cancelada(self):
        from orders.services import mark_as_cancelled
        order = self.make_order()
        mark_as_cancelled(order)
        order.refresh_from_db()
        with self.assertRaises(PaymentError):
            start_transaction(
                order, return_url='https://x.cl/r',
                gateway=self.approved_gateway(order),
            )

    def test_fallo_de_la_pasarela_no_deja_transaccion_local(self):
        order = self.make_order()
        with self.assertRaises(PaymentError):
            start_transaction(
                order, return_url='https://x.cl/r',
                gateway=FakeGateway(fail_on_create=True),
            )
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_reintento_tras_rechazo_vuelve_a_pendiente(self):
        order = self.make_order()
        gateway = self.rejected_gateway(order)
        start_transaction(order, return_url='https://x.cl/r', gateway=gateway)
        confirm_transaction('token-' + order.order_number, gateway=gateway)

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PAYMENT_REJECTED)


# ===========================================================================
# Confirmación
# ===========================================================================
class ConfirmTransactionTests(PaymentTestCase):
    def setUp(self):
        self.order = self.make_order(2)
        self.token = 'token-' + self.order.order_number

    def start(self, gateway):
        start_transaction(self.order, return_url='https://x.cl/r', gateway=gateway)
        return gateway

    def test_pago_aprobado_marca_la_orden(self):
        gateway = self.start(self.approved_gateway(self.order))
        payment = confirm_transaction(self.token, gateway=gateway)

        self.assertEqual(payment.status, PaymentStatus.AUTHORIZED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID)
        self.assertIsNotNone(self.order.paid_at)

    def test_pago_aprobado_descuenta_stock(self):
        gateway = self.start(self.approved_gateway(self.order))
        confirm_transaction(self.token, gateway=gateway)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 18)
        self.assertEqual(self.variant.reserved, 0)

    def test_pago_aprobado_guarda_los_datos_de_la_transaccion(self):
        gateway = self.start(self.approved_gateway(self.order))
        payment = confirm_transaction(self.token, gateway=gateway)

        self.assertEqual(payment.authorization_code, '123456')
        self.assertEqual(payment.payment_type_code, 'VN')
        self.assertEqual(payment.card_last_digits, '6623')

    def test_pago_rechazado_marca_la_orden(self):
        gateway = self.start(self.rejected_gateway(self.order))
        payment = confirm_transaction(self.token, gateway=gateway)

        self.assertEqual(payment.status, PaymentStatus.REJECTED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAYMENT_REJECTED)

    def test_pago_rechazado_libera_el_stock(self):
        gateway = self.start(self.rejected_gateway(self.order))
        confirm_transaction(self.token, gateway=gateway)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 20)
        self.assertEqual(self.variant.reserved, 0)

    def test_doble_confirmacion_no_descuenta_stock_dos_veces(self):
        gateway = self.start(self.approved_gateway(self.order))
        confirm_transaction(self.token, gateway=gateway)
        confirm_transaction(self.token, gateway=gateway)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 18)

    def test_doble_confirmacion_no_llama_a_transbank_de_nuevo(self):
        gateway = self.start(self.approved_gateway(self.order))
        confirm_transaction(self.token, gateway=gateway)
        confirm_transaction(self.token, gateway=gateway)
        self.assertEqual(len(gateway.commit_calls), 1)

    def test_doble_confirmacion_no_crea_dos_pagos(self):
        gateway = self.start(self.approved_gateway(self.order))
        confirm_transaction(self.token, gateway=gateway)
        confirm_transaction(self.token, gateway=gateway)
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_token_desconocido_falla(self):
        with self.assertRaises(PaymentError):
            confirm_transaction('token-inventado', gateway=FakeGateway())

    def test_monto_distinto_se_rechaza(self):
        """Si Transbank informa otro monto, la orden no se marca pagada."""
        gateway = FakeGateway(commit_response=webpay_response(
            amount=1, buy_order=self.order.order_number,
        ))
        self.start(gateway)
        with self.assertRaises(PaymentError):
            confirm_transaction(self.token, gateway=gateway)

        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.PAID)

    def test_monto_distinto_marca_la_transaccion_como_error(self):
        gateway = FakeGateway(commit_response=webpay_response(
            amount=1, buy_order=self.order.order_number,
        ))
        self.start(gateway)
        with self.assertRaises(PaymentError):
            confirm_transaction(self.token, gateway=gateway)
        self.assertEqual(
            PaymentTransaction.objects.get().status, PaymentStatus.ERROR,
        )

    def test_buy_order_distinto_se_rechaza(self):
        gateway = FakeGateway(commit_response=webpay_response(
            amount=self.order.total, buy_order='GF-OTRA-ORDEN',
        ))
        self.start(gateway)
        with self.assertRaises(PaymentError):
            confirm_transaction(self.token, gateway=gateway)

        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.PAID)

    def test_fallo_de_comunicacion_marca_error_y_no_paga(self):
        gateway = self.start(FakeGateway(fail_on_commit=True))
        with self.assertRaises(PaymentError):
            confirm_transaction(self.token, gateway=gateway)

        self.assertEqual(
            PaymentTransaction.objects.get().status, PaymentStatus.ERROR,
        )
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.PAID)

    def test_fallo_de_comunicacion_no_libera_el_stock(self):
        """Un error de red no debe descuadrar el inventario reservado."""
        gateway = self.start(FakeGateway(fail_on_commit=True))
        with self.assertRaises(PaymentError):
            confirm_transaction(self.token, gateway=gateway)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 2)


class CancelAndExpireTests(PaymentTestCase):
    def setUp(self):
        self.order = self.make_order(2)
        self.gateway = self.approved_gateway(self.order)
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        self.payment = PaymentTransaction.objects.get()

    def cancel(self, token=None):
        return cancel_transaction(
            buy_order=self.order.order_number,
            token=self.payment.token if token is None else token,
        )

    def expire(self, session_id=None):
        return expire_transaction(
            buy_order=self.order.order_number,
            session_id=self.payment.session_id if session_id is None else session_id,
        )

    # -- Anulación ----------------------------------------------------------
    def test_anulacion_deja_la_orden_reintentable(self):
        self.cancel()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAYMENT_REJECTED)
        self.assertTrue(self.order.can_retry_payment)

    def test_anulacion_libera_el_stock(self):
        self.cancel()
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 0)

    def test_anulacion_marca_la_transaccion(self):
        self.cancel()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CANCELLED)

    def test_anulacion_repetida_es_idempotente(self):
        self.cancel()
        self.cancel()
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 0)
        self.assertEqual(self.variant.stock, 20)

    def test_anulacion_de_orden_inexistente_no_rompe(self):
        self.assertIsNone(cancel_transaction(buy_order='GF-NO-EXISTE', token='x'))

    def test_anulacion_sin_token_se_ignora(self):
        self.assertIsNone(
            cancel_transaction(buy_order=self.order.order_number, token='')
        )

    def test_anulacion_con_token_falso_no_toca_la_orden(self):
        """Seguridad: nadie puede anular una orden ajena adivinando su número."""
        self.assertIsNone(self.cancel(token='token-inventado'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 2)

    def test_anulacion_no_afecta_una_orden_pagada(self):
        confirm_transaction(self.payment.token, gateway=self.gateway)
        self.cancel()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID)

    def test_anulacion_no_afecta_un_pago_en_confirmacion(self):
        PaymentTransaction.objects.filter(pk=self.payment.pk).update(
            status=PaymentStatus.PROCESSING,
        )
        self.cancel()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    # -- Expiración ---------------------------------------------------------
    def test_expiracion_deja_la_orden_reintentable(self):
        self.expire()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAYMENT_REJECTED)

    def test_expiracion_marca_la_transaccion(self):
        self.expire()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.EXPIRED)

    def test_expiracion_libera_el_stock(self):
        self.expire()
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 0)

    def test_expiracion_de_orden_inexistente_no_rompe(self):
        self.assertIsNone(
            expire_transaction(buy_order='GF-NO-EXISTE', session_id='x')
        )

    def test_expiracion_con_sesion_falsa_no_toca_la_orden(self):
        """Seguridad: el id de sesión aleatorio actúa como comprobante."""
        self.assertIsNone(self.expire(session_id='sesion-inventada'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    def test_expiracion_nunca_confirma_el_pago(self):
        self.expire()
        self.assertEqual(len(self.gateway.commit_calls), 0)

    def test_se_puede_reintentar_tras_anular(self):
        self.cancel()
        self.order.refresh_from_db()
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 2)


# ===========================================================================
# Vistas del retorno de Webpay
# ===========================================================================
class PaymentReturnViewTests(PaymentTestCase):
    def setUp(self):
        self.order = self.make_order(2)
        self.gateway = self.approved_gateway(self.order)
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        self.token = 'token-' + self.order.order_number

    def test_retorno_sin_parametros_redirige_al_inicio(self):
        response = self.client.get(reverse('payments:return'))
        self.assertRedirects(response, reverse('store:home'))

    def test_retorno_con_token_aprobado_lleva_a_exito(self):
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = self.client.get(
                reverse('payments:return'), {'token_ws': self.token},
            )
        self.assert_result_redirect(response, 'payments:success', self.order)

    def test_retorno_con_token_rechazado_lleva_a_fallo(self):
        gateway = self.rejected_gateway(self.order)
        with patch('payments.services.get_gateway', return_value=gateway):
            response = self.client.get(
                reverse('payments:return'), {'token_ws': self.token},
            )
        self.assert_result_redirect(response, 'payments:failure', self.order)

    def test_retorno_por_post_no_reemplaza_la_sesion(self):
        """Transbank vuelve por POST sin cookies (SameSite).

        Si el retorno escribiera en la sesión, Django emitiría una sesión
        nueva y el cliente perdería su cuenta y su carrito.
        """
        cliente = self.client_class()
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = cliente.post(
                reverse('payments:return'), {'token_ws': self.token},
            )
        self.assertNotIn('sessionid', response.cookies)

    def test_enlace_firmado_da_acceso_a_quien_vuelve_de_webpay(self):
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = self.client_class().get(
                reverse('payments:return'), {'token_ws': self.token},
            )
        # Otro navegador sin sesión previa sigue el enlace de la redirección.
        visitante = self.client_class()
        success = visitante.get(response['Location'])
        self.assertEqual(success.status_code, 200)
        # Y queda recordado en su sesión para verla sin el enlace.
        again = visitante.get(
            reverse('payments:success', args=[self.order.order_number])
        )
        self.assertEqual(again.status_code, 200)

    def test_enlace_firmado_manipulado_no_da_acceso(self):
        url = reverse('payments:success', args=[self.order.order_number])
        response = self.client_class().get(url, {'acceso': 'firma-falsa'})
        self.assertEqual(response.status_code, 404)

    def test_enlace_firmado_de_otra_orden_no_sirve(self):
        from payments.views import sign_order_access
        otra = self.make_order(1)
        firma_ajena = sign_order_access(otra)
        url = reverse('payments:failure', args=[self.order.order_number])
        response = self.client_class().get(url, {'acceso': firma_ajena})
        self.assertEqual(response.status_code, 404)

    def test_retorno_acepta_post(self):
        """Transbank usa POST en el ambiente de integración."""
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = self.client.post(
                reverse('payments:return'), {'token_ws': self.token},
            )
        self.assertEqual(response.status_code, 302)

    def test_retorno_no_acepta_put(self):
        response = self.client.put(reverse('payments:return'))
        self.assertEqual(response.status_code, 405)

    def test_retorno_no_requiere_csrf(self):
        """Quien llama es Transbank, no un formulario del sitio."""
        cliente = self.client_class(enforce_csrf_checks=True)
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = cliente.post(
                reverse('payments:return'), {'token_ws': self.token},
            )
        self.assertNotEqual(response.status_code, 403)

    def test_anulacion_del_usuario(self):
        payment = PaymentTransaction.objects.get()
        response = self.client.post(reverse('payments:return'), {
            'TBK_TOKEN': payment.token,
            'TBK_ORDEN_COMPRA': self.order.order_number,
            'TBK_ID_SESION': payment.session_id,
        })
        self.assert_result_redirect(response, 'payments:failure', self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAYMENT_REJECTED)

    def test_expiracion_por_tiempo(self):
        payment = PaymentTransaction.objects.get()
        response = self.client.post(reverse('payments:return'), {
            'TBK_ORDEN_COMPRA': self.order.order_number,
            'TBK_ID_SESION': payment.session_id,
        })
        self.assert_result_redirect(response, 'payments:failure', self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAYMENT_REJECTED)

    def test_anulacion_forjada_no_cancela_ni_da_acceso(self):
        """Seguridad: enviar el número de una orden ajena no sirve de nada."""
        atacante = self.client_class()
        response = atacante.post(reverse('payments:return'), {
            'TBK_TOKEN': 'lo-que-sea',
            'TBK_ORDEN_COMPRA': self.order.order_number,
            'TBK_ID_SESION': 'lo-que-sea',
        })
        self.assertRedirects(response, reverse('store:home'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        # Y sigue sin poder ver los datos personales de la orden.
        detalle = atacante.get(
            reverse('payments:failure', args=[self.order.order_number])
        )
        self.assertEqual(detalle.status_code, 404)

    def test_expiracion_forjada_no_cancela(self):
        response = self.client_class().post(reverse('payments:return'), {
            'TBK_ORDEN_COMPRA': self.order.order_number,
            'TBK_ID_SESION': 'sesion-adivinada',
        })
        self.assertRedirects(response, reverse('store:home'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    def test_doble_token_se_trata_como_fallo(self):
        response = self.client.post(reverse('payments:return'), {
            'token_ws': self.token,
            'TBK_TOKEN': 'abc',
            'TBK_ORDEN_COMPRA': self.order.order_number,
        })
        self.assert_result_redirect(response, 'payments:failure', self.order)

    def test_doble_token_nunca_confirma_el_pago(self):
        self.client.post(reverse('payments:return'), {
            'token_ws': self.token,
            'TBK_TOKEN': 'abc',
            'TBK_ORDEN_COMPRA': self.order.order_number,
        })
        self.assertEqual(len(self.gateway.commit_calls), 0)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.PAID)

    def test_el_frontend_no_puede_declarar_un_pago_exitoso(self):
        """Inventar parámetros de éxito no debe pagar la orden."""
        self.client.post(reverse('payments:return'), {
            'token_ws': 'token-falso',
            'status': 'AUTHORIZED',
            'response_code': '0',
        })
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, OrderStatus.PAID)


class PaymentPageTests(PaymentTestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.order = self.make_order(2, user=self.user)
        self.gateway = self.approved_gateway(self.order)

    def test_pagina_de_exito_requiere_orden_pagada(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:success', args=[self.order.order_number])
        )
        self.assertRedirects(
            response,
            reverse('payments:failure', args=[self.order.order_number]),
        )

    def test_pagina_de_exito_tras_pagar(self):
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        confirm_transaction('token-' + self.order.order_number, gateway=self.gateway)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:success', args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

    def test_pagina_de_exito_no_expone_el_token(self):
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        confirm_transaction('token-' + self.order.order_number, gateway=self.gateway)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:success', args=[self.order.order_number])
        )
        self.assertNotContains(response, 'token-' + self.order.order_number)

    def test_otro_usuario_no_ve_la_pagina_de_exito(self):
        otro = User.objects.create_user('beto', 'beto@test.cl', 'ClaveSegura123')
        self.client.force_login(otro)
        response = self.client.get(
            reverse('payments:success', args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 404)

    def test_otro_usuario_no_puede_iniciar_el_pago(self):
        otro = User.objects.create_user('beto', 'beto@test.cl', 'ClaveSegura123')
        self.client.force_login(otro)
        response = self.client.get(
            reverse('payments:start', args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 404)

    def test_pagina_de_fallo_muestra_el_motivo(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:failure', args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no se completó')

    def test_pagina_de_fallo_no_muestra_datos_tecnicos(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:failure', args=[self.order.order_number])
        )
        self.assertNotContains(response, 'response_code')

    def test_iniciar_pago_muestra_el_puente_a_webpay(self):
        self.client.force_login(self.user)
        with patch('payments.services.get_gateway', return_value=self.gateway):
            response = self.client.get(
                reverse('payments:start', args=[self.order.order_number])
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'token_ws')

    def test_orden_pagada_redirige_desde_iniciar_pago(self):
        start_transaction(
            self.order, return_url='https://x.cl/r', gateway=self.gateway,
        )
        confirm_transaction('token-' + self.order.order_number, gateway=self.gateway)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('payments:start', args=[self.order.order_number])
        )
        self.assertRedirects(
            response,
            reverse('payments:success', args=[self.order.order_number]),
        )


class PaymentModelTests(PaymentTestCase):
    def test_no_puede_haber_dos_pagos_autorizados_por_orden(self):
        """Restricción de base de datos contra el doble cobro."""
        from django.db import IntegrityError, transaction as db_transaction

        order = self.make_order()
        PaymentTransaction.objects.create(
            order=order, token='t1', buy_order=order.order_number,
            amount=order.total, status=PaymentStatus.AUTHORIZED,
        )
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                PaymentTransaction.objects.create(
                    order=order, token='t2', buy_order=order.order_number,
                    amount=order.total, status=PaymentStatus.AUTHORIZED,
                )

    def test_si_se_permiten_varios_intentos_no_autorizados(self):
        order = self.make_order()
        PaymentTransaction.objects.create(
            order=order, token='t1', buy_order=order.order_number,
            amount=order.total, status=PaymentStatus.REJECTED,
        )
        PaymentTransaction.objects.create(
            order=order, token='t2', buy_order=order.order_number,
            amount=order.total, status=PaymentStatus.REJECTED,
        )
        self.assertEqual(PaymentTransaction.objects.count(), 2)

    def test_el_token_es_unico(self):
        from django.db import IntegrityError, transaction as db_transaction

        order = self.make_order()
        PaymentTransaction.objects.create(
            order=order, token='mismo', buy_order=order.order_number,
            amount=order.total,
        )
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                PaymentTransaction.objects.create(
                    order=order, token='mismo', buy_order=order.order_number,
                    amount=order.total,
                )

    def test_tipo_de_pago_legible(self):
        order = self.make_order()
        payment = PaymentTransaction.objects.create(
            order=order, token='t', buy_order=order.order_number,
            amount=order.total, payment_type_code='VD',
        )
        self.assertEqual(payment.payment_type_display, 'Débito')

    def test_tarjeta_enmascarada(self):
        order = self.make_order()
        payment = PaymentTransaction.objects.create(
            order=order, token='t', buy_order=order.order_number,
            amount=order.total, card_last_digits='6623',
        )
        self.assertIn('6623', payment.masked_card)
        self.assertIn('••••', payment.masked_card)

    def test_tarjeta_enmascarada_sin_datos(self):
        order = self.make_order()
        payment = PaymentTransaction.objects.create(
            order=order, token='t', buy_order=order.order_number,
            amount=order.total,
        )
        self.assertEqual(payment.masked_card, '—')


@override_settings(TRANSBANK_ENVIRONMENT='integration')
class ConfigurationTests(TestCase):
    def test_las_credenciales_no_estan_en_el_codigo_de_las_vistas(self):
        """Las credenciales solo se leen de la configuración."""
        from pathlib import Path
        source = Path(__file__).resolve().parent / 'views.py'
        contenido = source.read_text(encoding='utf-8')
        self.assertNotIn('TRANSBANK_API_KEY', contenido)
        self.assertNotIn('597055555532', contenido)

    def test_la_api_key_por_defecto_es_la_oficial_de_integracion(self):
        from django.conf import settings
        self.assertTrue(settings.TRANSBANK_API_KEY.startswith('579B532A7440BB0C'))
