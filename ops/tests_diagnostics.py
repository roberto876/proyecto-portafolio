"""Pruebas del panel «Estado de la tienda»."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from ops.diagnostics import ERROR, OK, WARNING, Check, run_checks, summary
from store.models import StoreSettings


class DiagnosticsLogicTests(TestCase):
    def by_title(self, title):
        return next(check for check in run_checks() if check.title == title)

    def test_base_de_datos_ok(self):
        self.assertEqual(self.by_title('Base de datos').level, OK)

    def test_migraciones_al_dia(self):
        self.assertEqual(self.by_title('Estructura de datos').level, OK)

    @override_settings(TRANSBANK_ENVIRONMENT='integration')
    def test_pagos_de_prueba_es_advertencia(self):
        check = self.by_title('Pagos')
        self.assertEqual(check.level, WARNING)
        self.assertIn('PRUEBA', check.message)

    @override_settings(TRANSBANK_ENVIRONMENT='production')
    def test_pagos_en_produccion_ok(self):
        self.assertEqual(self.by_title('Pagos').level, OK)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
    def test_correo_smtp_ok(self):
        self.assertEqual(self.by_title('Correos').level, OK)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    def test_correo_desactivado_advierte(self):
        self.assertEqual(self.by_title('Correos').level, WARNING)

    def test_faltan_datos_legales(self):
        self.assertEqual(self.by_title('Datos legales').level, WARNING)

    def test_datos_legales_completos(self):
        StoreSettings.objects.update_or_create(
            pk=1, defaults={'legal_name': 'Ana SpA', 'rut': '76.123.456-7'},
        )
        self.assertEqual(self.by_title('Datos legales').level, OK)

    @override_settings(CRON_SECRET='')
    def test_cron_desactivado_advierte(self):
        self.assertEqual(self.by_title('Tareas automáticas').level, WARNING)

    @override_settings(SUPABASE_URL='', SUPABASE_SERVICE_ROLE_KEY='')
    def test_fotos_sin_configurar_advierte(self):
        self.assertEqual(self.by_title('Fotos de productos').level, WARNING)

    def test_catalogo_vacio_advierte(self):
        self.assertEqual(self.by_title('Catálogo').level, WARNING)

    def test_cada_advertencia_dice_que_hacer(self):
        for check in run_checks():
            if check.level in (WARNING, ERROR):
                with self.subTest(check=check.title):
                    self.assertTrue(check.fix, f'«{check.title}» no indica qué hacer')

    def test_resumen_toma_el_peor_nivel(self):
        self.assertEqual(summary([Check('a', OK, ''), Check('b', WARNING, '')]), WARNING)
        self.assertEqual(summary([Check('a', ERROR, ''), Check('b', WARNING, '')]), ERROR)
        self.assertEqual(summary([Check('a', OK, '')]), OK)


class DiagnosticsPageTests(TestCase):
    def test_requiere_ser_administrador(self):
        response = self.client.get(reverse('store_status'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_un_cliente_comun_no_entra(self):
        User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.client.login(username='ana', password='ClaveSegura123')
        response = self.client.get(reverse('store_status'))
        self.assertEqual(response.status_code, 302)

    def test_el_administrador_ve_el_estado(self):
        admin = User.objects.create_superuser('admin', 'a@test.cl', 'ClaveSegura123')
        self.client.force_login(admin)
        response = self.client.get(reverse('store_status'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Estado de la tienda')
        self.assertContains(response, 'Base de datos')

    def test_portada_del_admin_enlaza_al_estado(self):
        admin = User.objects.create_superuser('admin', 'a@test.cl', 'ClaveSegura123')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, reverse('store_status'))
        self.assertContains(response, 'Ajustes de la tienda')
