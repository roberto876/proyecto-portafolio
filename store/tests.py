"""Pruebas del catálogo: modelos, filtros, vistas y SEO."""
from django.test import TestCase
from django.urls import reverse

from store.models import (
    Category,
    Gender,
    Product,
    ProductImage,
    ProductVariant,
    Size,
    format_clp,
)
from store.services import DEFAULT_SORT, filter_products, parse_filters


class CatalogFactory:
    """Utilidades compartidas para construir datos de prueba."""

    @staticmethod
    def category(name='Poleras', **kwargs):
        return Category.objects.create(name=name, **kwargs)

    @staticmethod
    def product(category, name='Polera Test', price=19990, **kwargs):
        return Product.objects.create(
            category=category, name=name, price=price, **kwargs
        )

    @staticmethod
    def variant(product, size=Size.M, color='Negro', stock=10, **kwargs):
        return ProductVariant.objects.create(
            product=product, size=size, color=color, stock=stock, **kwargs
        )


# ===========================================================================
# Modelos
# ===========================================================================
class CategoryModelTests(TestCase):
    def test_slug_se_genera_desde_el_nombre(self):
        category = Category.objects.create(name='Calzas y Leggings')
        self.assertEqual(category.slug, 'calzas-y-leggings')

    def test_slug_explicito_se_respeta(self):
        category = Category.objects.create(name='Poleras', slug='custom')
        self.assertEqual(category.slug, 'custom')

    def test_str_devuelve_el_nombre(self):
        self.assertEqual(str(Category.objects.create(name='Shorts')), 'Shorts')

    def test_get_absolute_url_filtra_por_categoria(self):
        category = Category.objects.create(name='Shorts')
        self.assertIn('categoria=shorts', category.get_absolute_url())

    def test_manager_active_excluye_inactivas(self):
        Category.objects.create(name='Visible')
        Category.objects.create(name='Oculta', is_active=False)
        self.assertEqual(Category.objects.active().count(), 1)

    def test_orden_por_sort_order(self):
        Category.objects.create(name='B', sort_order=2)
        Category.objects.create(name='A', sort_order=1)
        self.assertEqual(
            list(Category.objects.values_list('name', flat=True)), ['A', 'B']
        )


class ProductModelTests(TestCase):
    def setUp(self):
        self.category = CatalogFactory.category()

    def test_slug_se_genera_automaticamente(self):
        product = CatalogFactory.product(self.category, name='Polera Performance')
        self.assertEqual(product.slug, 'polera-performance')

    def test_slug_duplicado_recibe_sufijo(self):
        first = CatalogFactory.product(self.category, name='Polera')
        second = CatalogFactory.product(self.category, name='Polera')
        self.assertEqual(first.slug, 'polera')
        self.assertEqual(second.slug, 'polera-2')

    def test_tercer_slug_duplicado_incrementa(self):
        for _ in range(3):
            CatalogFactory.product(self.category, name='Short')
        self.assertTrue(Product.objects.filter(slug='short-3').exists())

    def test_sku_se_genera_si_falta(self):
        product = CatalogFactory.product(self.category)
        self.assertTrue(product.sku.startswith('GF-'))
        self.assertEqual(len(product.sku), 11)

    def test_sku_explicito_se_respeta(self):
        product = CatalogFactory.product(self.category, sku='MI-SKU')
        self.assertEqual(product.sku, 'MI-SKU')

    def test_is_on_sale_verdadero_con_precio_anterior_mayor(self):
        product = CatalogFactory.product(self.category, price=10000, compare_price=20000)
        self.assertTrue(product.is_on_sale)

    def test_is_on_sale_falso_sin_precio_anterior(self):
        self.assertFalse(CatalogFactory.product(self.category).is_on_sale)

    def test_descuento_se_calcula_correctamente(self):
        product = CatalogFactory.product(self.category, price=15000, compare_price=20000)
        self.assertEqual(product.discount_percentage, 25)

    def test_descuento_es_cero_sin_oferta(self):
        self.assertEqual(CatalogFactory.product(self.category).discount_percentage, 0)

    def test_precio_formateado_usa_separador_de_miles_chileno(self):
        product = CatalogFactory.product(self.category, price=24990)
        self.assertEqual(product.price_formatted, '$24.990')

    def test_precio_formateado_con_millones(self):
        self.assertEqual(format_clp(1234567), '$1.234.567')

    def test_precio_formateado_de_cero(self):
        self.assertEqual(format_clp(0), '$0')

    def test_total_stock_suma_variantes_activas(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, size=Size.S, stock=5)
        CatalogFactory.variant(product, size=Size.M, stock=7)
        self.assertEqual(product.total_stock, 12)

    def test_total_stock_ignora_variantes_inactivas(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, size=Size.S, stock=5)
        CatalogFactory.variant(product, size=Size.M, stock=7, is_active=False)
        self.assertEqual(product.total_stock, 5)

    def test_total_stock_descuenta_lo_reservado(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, stock=10, reserved=4)
        self.assertEqual(product.total_stock, 6)

    def test_in_stock_falso_si_todo_esta_reservado(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, stock=3, reserved=3)
        self.assertFalse(product.in_stock)

    def test_tallas_disponibles_en_orden_correcto(self):
        product = CatalogFactory.product(self.category)
        for size in (Size.XL, Size.S, Size.M):
            CatalogFactory.variant(product, size=size, stock=3)
        self.assertEqual(product.available_sizes, ['S', 'M', 'XL'])

    def test_tallas_disponibles_excluye_sin_stock(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, size=Size.S, stock=0)
        CatalogFactory.variant(product, size=Size.M, stock=4)
        self.assertEqual(product.available_sizes, ['M'])

    def test_colores_disponibles_sin_duplicados(self):
        product = CatalogFactory.product(self.category)
        CatalogFactory.variant(product, size=Size.S, color='Negro', stock=2)
        CatalogFactory.variant(product, size=Size.M, color='Negro', stock=2)
        self.assertEqual(len(product.available_colors), 1)

    def test_galeria_incluye_imagen_principal_primero(self):
        product = CatalogFactory.product(self.category, main_image='https://a/1.jpg')
        ProductImage.objects.create(product=product, image='https://a/2.jpg')
        self.assertEqual(product.gallery_images, ['https://a/1.jpg', 'https://a/2.jpg'])

    def test_galeria_elimina_duplicados(self):
        product = CatalogFactory.product(self.category, main_image='https://a/1.jpg')
        ProductImage.objects.create(product=product, image='https://a/1.jpg')
        self.assertEqual(product.gallery_images, ['https://a/1.jpg'])

    def test_get_absolute_url_usa_el_slug(self):
        product = CatalogFactory.product(self.category, name='Polera Cool')
        self.assertEqual(product.get_absolute_url(), '/productos/polera-cool/')

    def test_queryset_on_sale_filtra_ofertas(self):
        CatalogFactory.product(self.category, name='Normal', price=10000)
        CatalogFactory.product(
            self.category, name='Oferta', price=8000, compare_price=12000
        )
        self.assertEqual(Product.objects.on_sale().count(), 1)


class ProductVariantModelTests(TestCase):
    def setUp(self):
        self.category = CatalogFactory.category()
        self.product = CatalogFactory.product(self.category, sku='GF-TEST')

    def test_sku_de_variante_se_genera(self):
        variant = CatalogFactory.variant(self.product, size=Size.M, color='Negro')
        self.assertEqual(variant.sku, 'GF-TEST-M-NEGRO')

    def test_stock_disponible_resta_reservado(self):
        variant = CatalogFactory.variant(self.product, stock=10, reserved=3)
        self.assertEqual(variant.available_stock, 7)

    def test_stock_disponible_nunca_es_negativo(self):
        variant = CatalogFactory.variant(self.product, stock=5, reserved=5)
        self.assertEqual(variant.available_stock, 0)

    def test_etiqueta_legible(self):
        variant = CatalogFactory.variant(self.product, size=Size.L, color='Blanco')
        self.assertEqual(variant.label, 'L / Blanco')

    def test_queryset_purchasable_excluye_agotadas(self):
        CatalogFactory.variant(self.product, size=Size.S, stock=0)
        CatalogFactory.variant(self.product, size=Size.M, stock=5)
        self.assertEqual(ProductVariant.objects.purchasable().count(), 1)

    def test_queryset_purchasable_excluye_totalmente_reservadas(self):
        CatalogFactory.variant(self.product, size=Size.S, stock=5, reserved=5)
        self.assertEqual(ProductVariant.objects.purchasable().count(), 0)


# ===========================================================================
# Servicio de filtrado
# ===========================================================================
class ParseFiltersTests(TestCase):
    def test_valores_por_defecto(self):
        filters = parse_filters({})
        self.assertEqual(filters.sort, DEFAULT_SORT)
        self.assertEqual(filters.query, '')
        self.assertFalse(filters.has_filters)

    def test_genero_invalido_se_descarta(self):
        self.assertEqual(parse_filters({'genero': 'X'}).gender, '')

    def test_genero_valido_se_acepta_en_minusculas(self):
        self.assertEqual(parse_filters({'genero': 'h'}).gender, 'H')

    def test_talla_invalida_se_descarta(self):
        self.assertEqual(parse_filters({'talla': 'ENORME'}).size, '')

    def test_talla_valida_se_normaliza(self):
        self.assertEqual(parse_filters({'talla': 'm'}).size, 'M')

    def test_orden_invalido_cae_al_por_defecto(self):
        self.assertEqual(parse_filters({'orden': 'hack'}).sort, DEFAULT_SORT)

    def test_precio_no_numerico_se_descarta(self):
        self.assertIsNone(parse_filters({'precio_min': 'abc'}).price_min)

    def test_precio_negativo_se_descarta(self):
        self.assertIsNone(parse_filters({'precio_min': '-500'}).price_min)

    def test_precio_absurdamente_alto_se_descarta(self):
        self.assertIsNone(parse_filters({'precio_max': '999999999999'}).price_max)

    def test_rango_invertido_se_corrige(self):
        filters = parse_filters({'precio_min': '50000', 'precio_max': '10000'})
        self.assertEqual((filters.price_min, filters.price_max), (10000, 50000))

    def test_busqueda_se_recorta_a_100_caracteres(self):
        self.assertEqual(len(parse_filters({'q': 'a' * 500}).query), 100)

    def test_has_filters_detecta_busqueda(self):
        self.assertTrue(parse_filters({'q': 'polera'}).has_filters)


class FilterProductsTests(TestCase):
    def setUp(self):
        self.poleras = CatalogFactory.category('Poleras')
        self.shorts = CatalogFactory.category('Shorts')

        self.barata = CatalogFactory.product(
            self.poleras, name='Polera Barata', price=9990, gender=Gender.HOMBRE,
        )
        self.cara = CatalogFactory.product(
            self.poleras, name='Polera Cara', price=49990, gender=Gender.MUJER,
            compare_price=59990,
        )
        self.short = CatalogFactory.product(
            self.shorts, name='Short Basico', price=19990, gender=Gender.UNISEX,
        )
        self.inactiva = CatalogFactory.product(
            self.poleras, name='Polera Oculta', price=1000, is_active=False,
        )

        CatalogFactory.variant(self.barata, size=Size.S, color='Negro', stock=5)
        CatalogFactory.variant(self.cara, size=Size.L, color='Blanco', stock=5)
        CatalogFactory.variant(self.short, size=Size.M, color='Negro', stock=5)

    def test_solo_devuelve_productos_activos(self):
        results = filter_products(parse_filters({}))
        self.assertNotIn(self.inactiva, results)
        self.assertEqual(results.count(), 3)

    def test_filtro_por_categoria(self):
        results = filter_products(parse_filters({'categoria': 'shorts'}))
        self.assertEqual(list(results), [self.short])

    def test_filtro_por_genero(self):
        results = filter_products(parse_filters({'genero': 'M'}))
        self.assertEqual(list(results), [self.cara])

    def test_filtro_por_talla(self):
        results = filter_products(parse_filters({'talla': 'L'}))
        self.assertEqual(list(results), [self.cara])

    def test_filtro_por_color(self):
        results = filter_products(parse_filters({'color': 'negro'}))
        self.assertEqual(results.count(), 2)

    def test_filtro_por_precio_minimo(self):
        results = filter_products(parse_filters({'precio_min': '15000'}))
        self.assertEqual(results.count(), 2)

    def test_filtro_por_precio_maximo(self):
        results = filter_products(parse_filters({'precio_max': '15000'}))
        self.assertEqual(list(results), [self.barata])

    def test_filtro_por_rango_de_precio(self):
        results = filter_products(
            parse_filters({'precio_min': '15000', 'precio_max': '25000'})
        )
        self.assertEqual(list(results), [self.short])

    def test_busqueda_por_nombre(self):
        results = filter_products(parse_filters({'q': 'Barata'}))
        self.assertEqual(list(results), [self.barata])

    def test_busqueda_es_insensible_a_mayusculas(self):
        self.assertEqual(filter_products(parse_filters({'q': 'BARATA'})).count(), 1)

    def test_busqueda_por_categoria(self):
        self.assertEqual(filter_products(parse_filters({'q': 'Shorts'})).count(), 1)

    def test_busqueda_sin_resultados(self):
        self.assertEqual(filter_products(parse_filters({'q': 'inexistente'})).count(), 0)

    def test_orden_por_precio_ascendente(self):
        results = filter_products(parse_filters({'orden': 'precio_asc'}))
        self.assertEqual(results.first(), self.barata)

    def test_orden_por_precio_descendente(self):
        results = filter_products(parse_filters({'orden': 'precio_desc'}))
        self.assertEqual(results.first(), self.cara)

    def test_orden_por_nombre(self):
        results = filter_products(parse_filters({'orden': 'nombre'}))
        self.assertEqual(results.first(), self.barata)

    def test_orden_por_mas_vendidos(self):
        self.short.sales_count = 99
        self.short.save(update_fields=['sales_count'])
        results = filter_products(parse_filters({'orden': 'vendidos'}))
        self.assertEqual(results.first(), self.short)

    def test_solo_ofertas(self):
        results = filter_products(parse_filters({}, on_sale=True))
        self.assertEqual(list(results), [self.cara])

    def test_filtros_combinados(self):
        results = filter_products(
            parse_filters({'categoria': 'poleras', 'genero': 'H'})
        )
        self.assertEqual(list(results), [self.barata])

    def test_filtro_de_talla_no_duplica_resultados(self):
        # Dos variantes de talla M en el mismo producto no deben duplicarlo.
        CatalogFactory.variant(self.short, size=Size.M, color='Blanco', stock=3)
        results = filter_products(parse_filters({'talla': 'M'}))
        self.assertEqual(results.count(), 1)


# ===========================================================================
# Vistas
# ===========================================================================
class StoreViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CatalogFactory.category('Poleras')
        cls.product = CatalogFactory.product(
            cls.category, name='Polera Vista', price=19990, is_featured=True,
        )
        cls.variant = CatalogFactory.variant(cls.product, stock=10)

    def test_home_responde_200(self):
        response = self.client.get(reverse('store:home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

    def test_home_muestra_productos_destacados(self):
        response = self.client.get(reverse('store:home'))
        self.assertContains(response, 'Polera Vista')

    def test_catalogo_responde_200(self):
        response = self.client.get(reverse('store:product_list'))
        self.assertEqual(response.status_code, 200)

    def test_catalogo_pagina_invalida_devuelve_ultima(self):
        response = self.client.get(reverse('store:product_list'), {'pagina': '999'})
        self.assertEqual(response.status_code, 200)

    def test_catalogo_pagina_no_numerica_no_rompe(self):
        response = self.client.get(reverse('store:product_list'), {'pagina': 'abc'})
        self.assertEqual(response.status_code, 200)

    def test_ofertas_responde_200(self):
        self.assertEqual(self.client.get(reverse('store:offers')).status_code, 200)

    def test_detalle_de_producto_responde_200(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Polera Vista')

    def test_detalle_de_producto_inexistente_devuelve_404(self):
        response = self.client.get('/productos/no-existe/')
        self.assertEqual(response.status_code, 404)

    def test_detalle_de_producto_inactivo_devuelve_404(self):
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])
        response = self.client.get(self.product.get_absolute_url())
        self.assertEqual(response.status_code, 404)
        self.product.is_active = True
        self.product.save(update_fields=['is_active'])

    def test_paginas_institucionales_responden(self):
        for name in ('about', 'contact', 'terms', 'privacy', 'shipping'):
            with self.subTest(page=name):
                response = self.client.get(reverse(f'store:{name}'))
                self.assertEqual(response.status_code, 200)

    def test_pagina_404_personalizada(self):
        response = self.client.get('/ruta-que-no-existe/')
        self.assertEqual(response.status_code, 404)


class StoreApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CatalogFactory.category()
        cls.product = CatalogFactory.product(cls.category, name='Polera API')
        cls.variant = CatalogFactory.variant(
            cls.product, size=Size.M, color='Negro', stock=8,
        )

    def test_stock_de_variante_existente(self):
        response = self.client.get(
            reverse('store:variant_stock', args=[self.product.pk]),
            {'size': 'M', 'color': 'Negro'},
        )
        data = response.json()
        self.assertTrue(data['available'])
        self.assertEqual(data['stock'], 8)

    def test_stock_descuenta_reservado(self):
        self.variant.reserved = 5
        self.variant.save(update_fields=['reserved'])
        response = self.client.get(
            reverse('store:variant_stock', args=[self.product.pk]),
            {'size': 'M', 'color': 'Negro'},
        )
        self.assertEqual(response.json()['stock'], 3)
        self.variant.reserved = 0
        self.variant.save(update_fields=['reserved'])

    def test_stock_de_combinacion_inexistente(self):
        response = self.client.get(
            reverse('store:variant_stock', args=[self.product.pk]),
            {'size': 'XXL', 'color': 'Fucsia'},
        )
        self.assertFalse(response.json()['available'])

    def test_stock_rechaza_post(self):
        response = self.client.post(
            reverse('store:variant_stock', args=[self.product.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_sugerencias_requieren_dos_caracteres(self):
        response = self.client.get(reverse('store:search_suggestions'), {'q': 'a'})
        self.assertEqual(response.json()['results'], [])

    def test_sugerencias_devuelven_coincidencias(self):
        response = self.client.get(reverse('store:search_suggestions'), {'q': 'Polera'})
        self.assertEqual(len(response.json()['results']), 1)

    def test_sugerencias_sin_parametro(self):
        response = self.client.get(reverse('store:search_suggestions'))
        self.assertEqual(response.json()['results'], [])

    def test_sugerencias_no_exponen_datos_sensibles(self):
        response = self.client.get(reverse('store:search_suggestions'), {'q': 'Polera'})
        keys = set(response.json()['results'][0])
        self.assertEqual(keys, {'name', 'price', 'image', 'url', 'category'})


class ContactFormTests(TestCase):
    def test_formulario_valido_se_envia(self):
        response = self.client.post(reverse('store:contact'), {
            'name': 'Ana', 'email': 'ana@test.cl',
            'subject': 'Consulta', 'message': 'Hola',
        })
        self.assertRedirects(response, reverse('store:contact'))

    def test_honeypot_rechaza_bots(self):
        response = self.client.post(reverse('store:contact'), {
            'name': 'Bot', 'email': 'bot@test.cl', 'subject': 'Spam',
            'message': 'Spam', 'website': 'http://spam.com',
        })
        self.assertEqual(response.status_code, 200)

    def test_email_invalido_no_pasa(self):
        response = self.client.post(reverse('store:contact'), {
            'name': 'Ana', 'email': 'no-es-email',
            'subject': 'Consulta', 'message': 'Hola',
        })
        self.assertEqual(response.status_code, 200)


class SeoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = CatalogFactory.category()
        cls.product = CatalogFactory.product(category, name='Polera SEO')
        CatalogFactory.variant(cls.product)

    def test_sitemap_responde_xml(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])

    def test_sitemap_incluye_el_producto(self):
        response = self.client.get('/sitemap.xml')
        self.assertContains(response, self.product.slug)

    def test_robots_responde_texto_plano(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')

    def test_robots_bloquea_rutas_privadas(self):
        response = self.client.get('/robots.txt')
        for path in ('/admin/', '/carrito/', '/pagos/', '/cuenta/'):
            self.assertContains(response, f'Disallow: {path}')

    def test_robots_declara_el_sitemap(self):
        self.assertContains(self.client.get('/robots.txt'), 'Sitemap:')

    def test_detalle_incluye_canonical(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'rel="canonical"')

    def test_detalle_incluye_open_graph(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'property="og:title"')

    def test_detalle_incluye_datos_estructurados(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'application/ld+json')

    def test_carrito_lleva_noindex(self):
        response = self.client.get(reverse('cart:detail'))
        self.assertContains(response, 'noindex')

    def test_home_no_lleva_noindex(self):
        response = self.client.get(reverse('store:home'))
        self.assertNotContains(response, 'name="robots"')


class SecurityHeadersTests(TestCase):
    def test_csp_presente(self):
        response = self.client.get(reverse('store:home'))
        self.assertIn('Content-Security-Policy', response)

    def test_csp_bloquea_scripts_externos(self):
        response = self.client.get(reverse('store:home'))
        self.assertIn("script-src 'self'", response['Content-Security-Policy'])

    def test_csp_prohibe_ser_embebido(self):
        response = self.client.get(reverse('store:home'))
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])

    def test_csp_permite_form_action_a_transbank(self):
        response = self.client.get(reverse('store:home'))
        self.assertIn('webpay3g', response['Content-Security-Policy'])

    def test_nosniff_presente(self):
        response = self.client.get(reverse('store:home'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_permissions_policy_presente(self):
        response = self.client.get(reverse('store:home'))
        self.assertIn('Permissions-Policy', response)

    def test_admin_no_recibe_csp_restrictiva(self):
        # El admin de Django usa estilos en línea propios.
        response = self.client.get('/admin/login/')
        self.assertNotIn('Content-Security-Policy', response)

    def test_csp_permite_estilos_en_linea(self):
        """Los colores de variante y anchos dinámicos son estilos en línea.

        Sin `unsafe-inline` en `style-src`, el navegador bloquea todos los
        atributos `style` y la tienda se ve sin maquetar.
        """
        response = self.client.get(reverse('store:home'))
        self.assertIn("style-src 'self' 'unsafe-inline'",
                      response['Content-Security-Policy'])


class CsrfCookieTests(TestCase):
    """La cookie CSRF debe existir en toda página que permita usar el carrito.

    Regresión: la ficha de producto no tiene formularios, así que Django no
    emitía la cookie y el botón «Agregar al carrito» respondía 403 a cualquier
    visitante nuevo.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name='Poleras')
        cls.product = Product.objects.create(
            category=category, name='Polera CSRF', price=19990,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, size=Size.M, color='Negro', stock=5,
        )

    def assert_sets_csrf_cookie(self, url):
        response = self.client.get(url)
        self.assertIn(
            'csrftoken', response.cookies,
            msg=f'{url} no emitió la cookie CSRF',
        )

    def test_portada_emite_la_cookie(self):
        self.assert_sets_csrf_cookie(reverse('store:home'))

    def test_catalogo_emite_la_cookie(self):
        self.assert_sets_csrf_cookie(reverse('store:product_list'))

    def test_ofertas_emite_la_cookie(self):
        self.assert_sets_csrf_cookie(reverse('store:offers'))

    def test_ficha_de_producto_emite_la_cookie(self):
        self.assert_sets_csrf_cookie(self.product.get_absolute_url())

    def test_carrito_emite_la_cookie(self):
        self.assert_sets_csrf_cookie(reverse('cart:detail'))

    def test_agregar_al_carrito_funciona_con_esa_cookie(self):
        """Recorrido real: visitar la ficha y agregar por AJAX."""
        cliente = self.client_class(enforce_csrf_checks=True)
        cliente.get(self.product.get_absolute_url())
        token = cliente.cookies['csrftoken'].value

        response = cliente.post(
            reverse('cart:add'),
            {'variant_id': self.variant.pk, 'quantity': 1},
            headers={'x-requested-with': 'XMLHttpRequest', 'x-csrftoken': token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cart']['count'], 1)
