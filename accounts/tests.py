"""Pruebas de cuentas: registro, sesión, perfil y seguridad de autenticación."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.forms import RegistrationForm, UserProfileForm
from accounts.models import UserProfile

VALID_SIGNUP = {
    'username': 'anasoto',
    'first_name': 'Ana',
    'last_name': 'Soto',
    'email': 'ana@test.cl',
    'password1': 'EntrenaFuerte2026',
    'password2': 'EntrenaFuerte2026',
}


class UserProfileModelTests(TestCase):
    def test_el_perfil_se_crea_con_el_usuario(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_la_senal_es_idempotente(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        user.first_name = 'Ana'
        user.save()
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_has_address_falso_sin_datos(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.assertFalse(user.profile.has_address)

    def test_has_address_verdadero_con_datos(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        profile = user.profile
        profile.region = 'Metropolitana de Santiago'
        profile.commune = 'Providencia'
        profile.address = 'Av. Siempreviva'
        profile.save()
        self.assertTrue(profile.has_address)

    def test_str_del_perfil(self):
        user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.assertIn('ana', str(user.profile))


class RegistrationFormTests(TestCase):
    def test_formulario_valido(self):
        self.assertTrue(RegistrationForm(data=VALID_SIGNUP).is_valid())

    def test_contrasenas_distintas_se_rechazan(self):
        form = RegistrationForm(data={**VALID_SIGNUP, 'password2': 'Otra12345678'})
        self.assertIn('password2', form.errors)

    def test_contrasena_corta_se_rechaza(self):
        form = RegistrationForm(data={
            **VALID_SIGNUP, 'password1': 'Corta1', 'password2': 'Corta1',
        })
        self.assertIn('password2', form.errors)

    def test_contrasena_solo_numerica_se_rechaza(self):
        form = RegistrationForm(data={
            **VALID_SIGNUP, 'password1': '12345678901', 'password2': '12345678901',
        })
        self.assertIn('password2', form.errors)

    def test_contrasena_comun_se_rechaza(self):
        form = RegistrationForm(data={
            **VALID_SIGNUP, 'password1': 'password123', 'password2': 'password123',
        })
        self.assertIn('password2', form.errors)

    def test_email_duplicado_se_rechaza(self):
        User.objects.create_user('otro', 'ana@test.cl', 'ClaveSegura123')
        form = RegistrationForm(data=VALID_SIGNUP)
        self.assertIn('email', form.errors)

    def test_email_duplicado_ignora_mayusculas(self):
        User.objects.create_user('otro', 'ANA@TEST.CL', 'ClaveSegura123')
        form = RegistrationForm(data=VALID_SIGNUP)
        self.assertIn('email', form.errors)

    def test_usuario_duplicado_se_rechaza(self):
        User.objects.create_user('anasoto', 'otro@test.cl', 'ClaveSegura123')
        form = RegistrationForm(data=VALID_SIGNUP)
        self.assertIn('username', form.errors)

    def test_guarda_nombre_y_apellido(self):
        form = RegistrationForm(data=VALID_SIGNUP)
        form.is_valid()
        user = form.save()
        self.assertEqual(user.first_name, 'Ana')
        self.assertEqual(user.last_name, 'Soto')

    def test_la_contrasena_se_guarda_hasheada(self):
        form = RegistrationForm(data=VALID_SIGNUP)
        form.is_valid()
        user = form.save()
        self.assertNotEqual(user.password, VALID_SIGNUP['password1'])
        self.assertTrue(user.check_password(VALID_SIGNUP['password1']))


class RegistrationViewTests(TestCase):
    def test_pagina_de_registro_responde(self):
        self.assertEqual(
            self.client.get(reverse('accounts:register')).status_code, 200,
        )

    def test_registro_valido_crea_usuario(self):
        self.client.post(reverse('accounts:register'), VALID_SIGNUP)
        self.assertTrue(User.objects.filter(username='anasoto').exists())

    def test_registro_valido_inicia_sesion(self):
        self.client.post(reverse('accounts:register'), VALID_SIGNUP)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)

    def test_registro_invalido_no_crea_usuario(self):
        self.client.post(reverse('accounts:register'), {
            **VALID_SIGNUP, 'password2': 'distinta',
        })
        self.assertFalse(User.objects.filter(username='anasoto').exists())

    def test_registro_requiere_csrf(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        response = cliente.post(reverse('accounts:register'), VALID_SIGNUP)
        self.assertEqual(response.status_code, 403)

    def test_usuario_autenticado_es_redirigido(self):
        User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')
        self.client.login(username='ana', password='ClaveSegura123')
        response = self.client.get(reverse('accounts:register'))
        self.assertRedirects(response, reverse('store:home'))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'ana', 'ana@test.cl', 'ClaveSegura123', first_name='Ana',
        )

    def test_pagina_de_login_responde(self):
        self.assertEqual(
            self.client.get(reverse('accounts:login')).status_code, 200,
        )

    def test_login_correcto(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'ana', 'password': 'ClaveSegura123',
        })
        self.assertRedirects(response, reverse('store:home'))

    def test_login_incorrecto_no_autentica(self):
        self.client.post(reverse('accounts:login'), {
            'username': 'ana', 'password': 'incorrecta',
        })
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)

    def test_login_de_usuario_inexistente(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'fantasma', 'password': 'loquesea123',
        })
        self.assertEqual(response.status_code, 200)

    def test_login_requiere_csrf(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        response = cliente.post(reverse('accounts:login'), {
            'username': 'ana', 'password': 'ClaveSegura123',
        })
        self.assertEqual(response.status_code, 403)

    def test_logout_solo_por_post(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.assertEqual(
            self.client.get(reverse('accounts:logout')).status_code, 405,
        )

    def test_logout_por_post_cierra_sesion(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:logout'))
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)

    def test_next_interno_se_respeta(self):
        response = self.client.post(
            reverse('accounts:login') + '?next=/productos/',
            {'username': 'ana', 'password': 'ClaveSegura123'},
        )
        self.assertRedirects(response, '/productos/')

    def test_next_externo_se_ignora(self):
        """Protección contra redirección abierta usada en phishing."""
        response = self.client.post(
            reverse('accounts:login') + '?next=https://sitio-malicioso.cl',
            {'username': 'ana', 'password': 'ClaveSegura123'},
        )
        self.assertRedirects(response, reverse('store:home'))

    def test_next_con_doble_barra_se_ignora(self):
        response = self.client.post(
            reverse('accounts:login') + '?next=//sitio-malicioso.cl',
            {'username': 'ana', 'password': 'ClaveSegura123'},
        )
        self.assertRedirects(response, reverse('store:home'))

    def test_next_con_javascript_se_ignora(self):
        response = self.client.post(
            reverse('accounts:login') + '?next=javascript:alert(1)',
            {'username': 'ana', 'password': 'ClaveSegura123'},
        )
        self.assertRedirects(response, reverse('store:home'))


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')

    def test_perfil_requiere_autenticacion(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cuenta/login/', response['Location'])

    def test_perfil_responde_al_usuario_autenticado(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.assertEqual(
            self.client.get(reverse('accounts:profile')).status_code, 200,
        )

    def test_actualizar_perfil(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:profile'), {
            'first_name': 'Ana', 'last_name': 'Soto', 'email': 'ana@test.cl',
            'phone': '+56912345678', 'region': 'Metropolitana de Santiago',
            'commune': 'Providencia', 'address': 'Av. Siempreviva',
            'address_number': '742',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Ana')
        self.assertEqual(self.user.profile.commune, 'Providencia')

    def test_comuna_incoherente_se_rechaza(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:profile'), {
            'first_name': 'Ana', 'last_name': 'Soto', 'email': 'ana@test.cl',
            'region': 'Metropolitana de Santiago', 'commune': 'Arica',
            'address': 'Av. Siempreviva', 'address_number': '742', 'phone': '',
        })
        self.user.profile.refresh_from_db()
        self.assertNotEqual(self.user.profile.commune, 'Arica')

    def test_email_de_otro_usuario_se_rechaza(self):
        User.objects.create_user('beto', 'beto@test.cl', 'ClaveSegura123')
        form = UserProfileForm(
            data={'email': 'beto@test.cl'},
            instance=self.user.profile, user=self.user,
        )
        self.assertIn('email', form.errors)

    def test_conservar_el_propio_email_es_valido(self):
        form = UserProfileForm(
            data={'email': 'ana@test.cl'},
            instance=self.user.profile, user=self.user,
        )
        self.assertNotIn('email', form.errors)


class PasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', 'ana@test.cl', 'ClaveSegura123')

    def test_cambio_de_contrasena_requiere_autenticacion(self):
        response = self.client.get(reverse('accounts:password_change'))
        self.assertEqual(response.status_code, 302)

    def test_cambio_de_contrasena_correcto(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:password_change'), {
            'old_password': 'ClaveSegura123',
            'new_password1': 'NuevaClaveFuerte2026',
            'new_password2': 'NuevaClaveFuerte2026',
        })
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NuevaClaveFuerte2026'))

    def test_cambio_con_contrasena_actual_incorrecta(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:password_change'), {
            'old_password': 'incorrecta',
            'new_password1': 'NuevaClaveFuerte2026',
            'new_password2': 'NuevaClaveFuerte2026',
        })
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ClaveSegura123'))

    def test_cambio_mantiene_la_sesion_activa(self):
        self.client.login(username='ana', password='ClaveSegura123')
        self.client.post(reverse('accounts:password_change'), {
            'old_password': 'ClaveSegura123',
            'new_password1': 'NuevaClaveFuerte2026',
            'new_password2': 'NuevaClaveFuerte2026',
        })
        self.assertEqual(
            self.client.get(reverse('accounts:profile')).status_code, 200,
        )

    def test_pagina_de_recuperacion_responde(self):
        self.assertEqual(
            self.client.get(reverse('accounts:password_reset')).status_code, 200,
        )

    def test_recuperacion_envia_correo(self):
        from django.core import mail
        self.client.post(reverse('accounts:password_reset'), {
            'email': 'ana@test.cl',
        })
        self.assertEqual(len(mail.outbox), 1)

    def test_recuperacion_no_revela_si_el_email_existe(self):
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'nadie@test.cl',
        })
        self.assertRedirects(response, reverse('accounts:password_reset_done'))

    def test_paginas_de_recuperacion_responden(self):
        for name in ('password_reset_done', 'password_reset_complete'):
            with self.subTest(page=name):
                response = self.client.get(reverse(f'accounts:{name}'))
                self.assertEqual(response.status_code, 200)
