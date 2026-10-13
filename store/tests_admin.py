"""Pruebas del panel: subida de fotos, variantes en bloque, stock y CSV."""
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.cart import Cart
from orders.services import create_order_from_cart
from payments.tests import CHECKOUT
from store.models import Category, Product, ProductVariant, Size
from store.storage import StorageError, detect_image_type, upload_image
from store.variants import create_variant_grid, guess_color_hex, parse_colors

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64
WEBP = b'RIFF\x00\x00\x00\x00WEBP' + b'0' * 64

STORAGE = {
    'SUPABASE_URL': 'https://abc.supabase.co',
    'SUPABASE_SERVICE_ROLE_KEY': 'eyJhbGciOiJIUzI1NiJ9.secreto',
    'SUPABASE_STORAGE_BUCKET': 'productos',
}


def upload(content, name='foto.jpg', content_type='image/jpeg'):
    return SimpleUploadedFile(name, content, content_type=content_type)


# ===========================================================================
# Subida de imágenes
# ===========================================================================
class ImageDetectionTests(TestCase):
    def test_reconoce_jpeg_png_y_webp(self):
        self.assertEqual(detect_image_type(JPEG[:16]), ('image/jpeg', 'jpg'))
        self.assertEqual(detect_image_type(PNG[:16]), ('image/png', 'png'))
        self.assertEqual(detect_image_type(WEBP[:16]), ('image/webp', 'webp'))

    def test_rechaza_archivos_disfrazados(self):
        self.assertIsNone(detect_image_type(b'<?php echo 1; ?>'))
        self.assertIsNone(detect_image_type(b'MZ\x90\x00'))  # ejecutable de Windows


@override_settings(**STORAGE)
class UploadImageTests(TestCase):
    def fake_response(self, status=200, text='{}'):
        response = MagicMock()
        response.status_code = status
        response.text = text
        return response

    @override_settings(SUPABASE_URL='', SUPABASE_SERVICE_ROLE_KEY='')
    def test_sin_configurar_explica_como_activarlo(self):
        with self.assertRaisesMessage(StorageError, 'GUIA.md'):
            upload_image(upload(JPEG))

    def test_rechaza_fotos_demasiado_grandes(self):
        big = upload(JPEG + b'0' * (5 * 1024 * 1024))
        with self.assertRaisesMessage(StorageError, '4 MB'):
            upload_image(big)

    def test_rechaza_lo_que_no_es_imagen(self):
        with self.assertRaisesMessage(StorageError, 'no es una imagen'):
            upload_image(upload(b'%PDF-1.7 documento', 'foto.jpg'))

    @patch('store.storage.requests.post')
    def test_sube_y_devuelve_la_url_publica(self, post):
        post.return_value = self.fake_response()
        url = upload_image(upload(JPEG), folder='productos')

        self.assertTrue(url.startswith(
            'https://abc.supabase.co/storage/v1/object/public/productos/productos/'
        ))
        self.assertTrue(url.endswith('.jpg'))
        endpoint = post.call_args.args[0]
        self.assertIn('/storage/v1/object/productos/productos/', endpoint)

    @patch('store.storage.requests.post')
    def test_el_nombre_lo_genera_el_servidor(self, post):
        post.return_value = self.fake_response()
        url = upload_image(upload(JPEG, name='../../etc/passwd.jpg'))
        self.assertNotIn('passwd', url)
        self.assertNotIn('..', url)

    @patch('store.storage.requests.post')
    def test_clave_jwt_se_envia_como_bearer(self, post):
        post.return_value = self.fake_response()
        upload_image(upload(PNG))
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['apikey'], STORAGE['SUPABASE_SERVICE_ROLE_KEY'])
        self.assertEqual(headers['Authorization'], f'Bearer {STORAGE["SUPABASE_SERVICE_ROLE_KEY"]}')
        self.assertEqual(headers['Content-Type'], 'image/png')

    @override_settings(SUPABASE_SERVICE_ROLE_KEY='sb_secret_nueva_clave')
    @patch('store.storage.requests.post')
    def test_clave_nueva_va_solo_en_apikey(self, post):
        post.return_value = self.fake_response()
        upload_image(upload(WEBP))
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['apikey'], 'sb_secret_nueva_clave')
        self.assertNotIn('Authorization', headers)

    @patch('store.storage.requests.post')
    def test_bucket_inexistente_explica_como_crearlo(self, post):
        post.return_value = self.fake_response(400, '{"error":"Bucket not found"}')
        with self.assertRaisesMessage(StorageError, 'New bucket'):
            upload_image(upload(JPEG))

    @patch('store.storage.requests.post')
    def test_clave_equivocada_lo_explica(self, post):
        post.return_value = self.fake_response(403, 'Unauthorized')
        with self.assertRaisesMessage(StorageError, 'service_role'):
            upload_image(upload(JPEG))

    @patch('store.storage.requests.post', side_effect=requests.ConnectionError('sin red'))
    def test_sin_conexion_da_mensaje_amable(self, post):
        with self.assertRaisesMessage(StorageError, 'No se pudo conectar'):
            upload_image(upload(JPEG))


# ===========================================================================
# Variantes en bloque
# ===========================================================================
class VariantToolsTests(TestCase):
    def test_colores_conocidos(self):
        self.assertEqual(guess_color_hex('Negro'), '#111111')
        self.assertEqual(guess_color_hex('  azul   MARINO '), '#1b2a4a')

    def test_color_desconocido_usa_gris(self):
        self.assertEqual(guess_color_hex('Tornasol galáctico'), '#999999')

    def test_parseo_de_colores(self):
        self.assertEqual(
            parse_colors('negro, Blanco;azul marino\n, ,NEGRO'),
            ['Negro', 'Blanco', 'Azul marino'],
        )

    def test_crea_todas_las_combinaciones(self):
        product = Product.objects.create(
            category=Category.objects.create(name='Poleras'), name='P', price=1000,
        )
        created = create_variant_grid(product, [Size.S, Size.M, Size.L], ['Negro', 'Blanco'], 5)
        self.assertEqual(created, 6)
        self.assertEqual(product.variants.count(), 6)
        self.assertTrue(all(v.stock == 5 for v in product.variants.all()))

    def test_no_toca_combinaciones_existentes(self):
        product = Product.objects.create(
            category=Category.objects.create(name='Poleras'), name='P', price=1000,
        )
        ProductVariant.objects.create(product=product, size=Size.M, color='Negro', stock=99)
        created = create_variant_grid(product, [Size.M, Size.L], ['Negro'], 5)
        self.assertEqual(created, 1)
        self.assertEqual(product.variants.get(size=Size.M).stock, 99)


# ===========================================================================
# Panel de administración
# ===========================================================================
class AdminPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('admin', 'a@test.cl', 'ClaveSegura123')
        cls.category = Category.objects.create(name='Poleras')

    def setUp(self):
        self.client.force_login(self.admin)

    def product_form(self, **overrides):
        """Datos mínimos del formulario de producto del admin, con inlines vacíos."""
        data = {
            'name': 'Polera Admin', 'slug': 'polera-admin', 'category': self.category.pk,
            'gender': 'U', 'description': '', 'price': '19990', 'compare_price': '',
            'sku': '', 'main_image': 'https://example.test/foto.jpg',
            'is_active': 'on', 'bulk_stock': '10',
            'variants-TOTAL_FORMS': '0', 'variants-INITIAL_FORMS': '0',
            'variants-MIN_NUM_FORMS': '0', 'variants-MAX_NUM_FORMS': '1000',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '1000',
        }
        data.update(overrides)
        return data

    def test_formulario_de_producto_carga(self):
        response = self.client.get(reverse('admin:store_product_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crear variantes rápido')
        self.assertContains(response, 'multipart/form-data')

    def test_crear_producto_con_variantes_en_bloque(self):
        response = self.client.post(reverse('admin:store_product_add'), self.product_form(
            bulk_sizes=['S', 'M', 'L'], bulk_colors='Negro, Blanco',
        ))
        self.assertEqual(response.status_code, 302, response.content[:2000])
        product = Product.objects.get(name='Polera Admin')
        self.assertEqual(product.variants.count(), 6)
        self.assertEqual(product.variants.get(size='S', color='Negro').color_hex, '#111111')

    def test_tallas_sin_colores_da_error_claro(self):
        response = self.client.post(reverse('admin:store_product_add'), self.product_form(
            bulk_sizes=['S'], bulk_colors='',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'al menos un color')

    def test_producto_sin_foto_pide_una(self):
        response = self.client.post(
            reverse('admin:store_product_add'), self.product_form(main_image=''),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sube una foto o pega el enlace')

    @override_settings(**STORAGE)
    @patch('store.storage.requests.post')
    def test_subir_foto_desde_el_panel(self, post):
        post.return_value = MagicMock(status_code=200, text='{}')
        response = self.client.post(reverse('admin:store_product_add'), self.product_form(
            main_image='', main_image_upload=upload(JPEG),
        ))
        self.assertEqual(response.status_code, 302, response.content[:2000])
        product = Product.objects.get(name='Polera Admin')
        self.assertIn('/storage/v1/object/public/productos/', product.main_image)

    def test_ajustes_se_abren_desde_la_lista(self):
        response = self.client.get(reverse('admin:store_storesettings_changelist'))
        self.assertEqual(response.status_code, 302)

    def test_filtro_de_stock_bajo(self):
        product = Product.objects.create(category=self.category, name='P', price=1000)
        ProductVariant.objects.create(product=product, size=Size.S, color='Negro', stock=2)
        ProductVariant.objects.create(product=product, size=Size.M, color='Negro', stock=50)
        response = self.client.get(
            reverse('admin:store_productvariant_changelist'), {'stock': 'bajo'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cl'].result_count, 1)

    def test_filtro_de_agotadas(self):
        product = Product.objects.create(category=self.category, name='P', price=1000)
        ProductVariant.objects.create(product=product, size=Size.S, color='Negro', stock=0)
        ProductVariant.objects.create(product=product, size=Size.M, color='Negro', stock=5, reserved=5)
        ProductVariant.objects.create(product=product, size=Size.L, color='Negro', stock=9)
        response = self.client.get(
            reverse('admin:store_productvariant_changelist'), {'stock': 'agotado'},
        )
        self.assertEqual(response.context['cl'].result_count, 2)

    def test_exportar_ordenes_a_csv(self):
        product = Product.objects.create(category=self.category, name='Polera CSV', price=10000)
        variant = ProductVariant.objects.create(product=product, size=Size.M, color='Negro', stock=5)
        request = type('Request', (), {})()
        self.client.get(reverse('store:home'))
        request.session = self.client.session
        cart = Cart(request)
        cart.add(variant.pk, 2)
        order = create_order_from_cart(cart=cart, data=CHECKOUT)

        response = self.client.post(reverse('admin:orders_order_changelist'), {
            'action': 'export_csv', '_selected_action': [order.pk],
        })
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8')
        self.assertTrue(content.startswith('﻿'), 'Falta el BOM para Excel')
        self.assertIn('Orden;Fecha;Estado', content)
        self.assertIn(order.order_number, content)
        self.assertIn('2 x Polera CSV (M/Negro)', content)
