"""Pruebas de los ajustes editables de la tienda."""
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.cart import Cart
from store.models import Category, Product, ProductVariant, Size, StoreSettings


class StoreSettingsModelTests(TestCase):
    def test_load_crea_el_registro_unico(self):
        self.assertEqual(StoreSettings.objects.count(), 0)
        StoreSettings.load()
        StoreSettings.load()
        self.assertEqual(StoreSettings.objects.count(), 1)

    @override_settings(SITE_NAME='MI TIENDA', SHIPPING_COST=3000, FREE_SHIPPING_THRESHOLD=50000)
    def test_valores_iniciales_desde_la_configuracion(self):
        store = StoreSettings.load()
        self.assertEqual(store.store_name, 'MI TIENDA')
        self.assertEqual(store.shipping_cost, 3000)
        self.assertEqual(store.free_shipping_threshold, 50000)

    def test_guardar_siempre_usa_el_mismo_registro(self):
        StoreSettings(store_name='Otra').save()
        StoreSettings(store_name='Otra más').save()
        self.assertEqual(StoreSettings.objects.count(), 1)
        self.assertEqual(StoreSettings.load().store_name, 'Otra más')

    def test_no_se_puede_borrar(self):
        store = StoreSettings.load()
        store.delete()
        self.assertEqual(StoreSettings.objects.count(), 1)

    def test_logo_destaca_la_parte_final(self):
        store = StoreSettings(store_name='GYMFORGE', name_accent='FORGE')
        self.assertEqual(store.logo_parts, ('GYM', 'FORGE'))

    def test_logo_sin_parte_destacada(self):
        store = StoreSettings(store_name='Mi Tienda', name_accent='')
        self.assertEqual(store.logo_parts, ('Mi Tienda', ''))

    def test_logo_con_parte_que_no_coincide(self):
        store = StoreSettings(store_name='Mi Tienda', name_accent='FORGE')
        self.assertEqual(store.logo_parts, ('Mi Tienda', ''))

    def test_url_de_whatsapp(self):
        store = StoreSettings(whatsapp_number='56912345678')
        self.assertEqual(store.whatsapp_url, 'https://wa.me/56912345678')

    def test_sin_whatsapp_no_hay_url(self):
        self.assertEqual(StoreSettings().whatsapp_url, '')

    def test_datos_legales_completos(self):
        self.assertFalse(StoreSettings().has_legal_info)
        self.assertTrue(StoreSettings(legal_name='Ana SpA', rut='76.123.456-7').has_legal_info)


class StoreSettingsStorefrontTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(category=category, name='Polera', price=10000)
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=20,
        )

    def configure(self, **fields):
        store = StoreSettings.load()
        for key, value in fields.items():
            setattr(store, key, value)
        store.save()
        return store

    def test_el_nombre_editado_aparece_en_la_tienda(self):
        self.configure(store_name='Fuerza Sur', name_accent='Sur')
        response = self.client.get(reverse('store:home'))
        self.assertContains(response, 'Fuerza <span>Sur</span>')
        self.assertContains(response, '<title>Fuerza Sur')

    def test_el_titulo_incluye_la_marca(self):
        self.configure(store_name='Fuerza Sur')
        response = self.client.get(reverse('store:product_list'))
        self.assertContains(response, '<title>Catálogo · Fuerza Sur</title>')

    def test_datos_legales_en_el_pie(self):
        self.configure(legal_name='Fuerza Sur SpA', rut='76.123.456-7', address='Av. Siempreviva 742')
        response = self.client.get(reverse('store:home'))
        self.assertContains(response, 'Fuerza Sur SpA')
        self.assertContains(response, 'RUT 76.123.456-7')
        self.assertContains(response, 'Av. Siempreviva 742')

    def test_boton_de_whatsapp_solo_si_esta_configurado(self):
        self.assertNotContains(self.client.get(reverse('store:home')), 'wa.me/')
        self.configure(whatsapp_number='56912345678')
        self.assertContains(self.client.get(reverse('store:home')), 'https://wa.me/56912345678')

    def test_redes_sociales_solo_si_estan_configuradas(self):
        self.assertNotContains(self.client.get(reverse('store:home')), 'aria-label="Instagram"')
        self.configure(instagram_url='https://instagram.com/fuerzasur')
        self.assertContains(self.client.get(reverse('store:home')), 'instagram.com/fuerzasur')

    def test_texto_de_anuncio_personalizado(self):
        self.configure(announcement_text='Cyber: 20% en todo')
        self.assertContains(self.client.get(reverse('store:home')), 'Cyber: 20% en todo')

    @override_settings(TRANSBANK_ENVIRONMENT='integration')
    def test_aviso_de_pagos_de_prueba(self):
        self.assertContains(self.client.get(reverse('store:home')), 'pagos son simulados')

    @override_settings(TRANSBANK_ENVIRONMENT='production')
    def test_sin_aviso_en_produccion(self):
        self.assertNotContains(self.client.get(reverse('store:home')), 'pagos son simulados')

    def test_costo_de_envio_editable_se_aplica_al_carrito(self):
        self.configure(shipping_cost=2500, free_shipping_threshold=100000)
        self.client.post(reverse('cart:add'), {'variant_id': self.variant.pk, 'quantity': 1})
        cart = self.client.get(reverse('cart:state')).json()['cart']
        self.assertEqual(cart['shipping_cost'], 2500)
        self.assertEqual(cart['total'], 12500)

    def test_umbral_de_envio_gratis_editable(self):
        self.configure(shipping_cost=2500, free_shipping_threshold=20000)
        self.client.post(reverse('cart:add'), {'variant_id': self.variant.pk, 'quantity': 2})
        cart = self.client.get(reverse('cart:state')).json()['cart']
        self.assertTrue(cart['has_free_shipping'])

    def test_umbral_cero_desactiva_el_envio_gratis(self):
        self.configure(shipping_cost=3000, free_shipping_threshold=0)
        self.client.post(reverse('cart:add'), {'variant_id': self.variant.pk, 'quantity': 10})
        cart = self.client.get(reverse('cart:state')).json()['cart']
        self.assertEqual(cart['shipping_cost'], 3000)
        self.assertFalse(cart['has_free_shipping'])
        self.assertEqual(cart['amount_for_free_shipping'], 0)

    def test_despacho_siempre_gratis(self):
        self.configure(shipping_cost=0)
        self.client.post(reverse('cart:add'), {'variant_id': self.variant.pk, 'quantity': 1})
        self.assertEqual(self.client.get(reverse('cart:state')).json()['cart']['shipping_cost'], 0)

    def test_una_sola_consulta_de_ajustes_por_pagina(self):
        StoreSettings.load()
        request = type('Request', (), {})()
        with self.assertNumQueries(1):
            StoreSettings.for_request(request)
            StoreSettings.for_request(request)
            StoreSettings.for_request(request)


class StoreSettingsAdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser('admin', 'a@test.cl', 'ClaveSegura123')
        self.client.force_login(self.admin)

    def test_la_lista_abre_directamente_el_formulario(self):
        response = self.client.get(reverse('admin:store_storesettings_changelist'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/change/', response['Location'])

    def test_el_formulario_de_ajustes_carga(self):
        store = StoreSettings.load()
        response = self.client.get(
            reverse('admin:store_storesettings_change', args=[store.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Razón social')

    def test_whatsapp_invalido_se_rechaza(self):
        store = StoreSettings.load()
        store.whatsapp_number = '+56 9 1234'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            store.full_clean()
