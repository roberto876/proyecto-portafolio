"""Formularios públicos de la tienda."""
import logging

from django import forms
from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger('django')


class ContactForm(forms.Form):
    """Formulario de contacto con honeypot antispam."""

    name = forms.CharField(
        label='Nombre', max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Tu nombre', 'autocomplete': 'name',
        }),
    )
    email = forms.EmailField(
        label='Email', max_length=150,
        widget=forms.EmailInput(attrs={
            'class': 'form-input', 'placeholder': 'tu@email.cl', 'autocomplete': 'email',
        }),
    )
    subject = forms.CharField(
        label='Asunto', max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': '¿En qué te ayudamos?',
        }),
    )
    message = forms.CharField(
        label='Mensaje', max_length=2000,
        widget=forms.Textarea(attrs={
            'class': 'form-input', 'rows': 6,
            'placeholder': 'Cuéntanos con detalle...',
        }),
    )
    # Campo señuelo: es invisible para las personas, los bots lo rellenan.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-honeypot', 'tabindex': '-1',
            'autocomplete': 'off', 'aria-hidden': 'true',
        }),
    )

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Mensaje descartado.')
        return ''

    def send(self, *, recipient: str = '', store_name: str = '') -> None:
        """Entrega el mensaje al buzón de la tienda.

        Se usa ``reply_to`` con el email del cliente para que el dueño pueda
        responder directamente desde su correo. Los fallos de envío no deben
        romper la página de contacto: se registran y se sigue.
        """
        data = self.cleaned_data
        message = EmailMessage(
            subject=f'[Contacto {store_name or settings.SITE_NAME}] {data["subject"]}',
            body=f'De: {data["name"]} <{data["email"]}>\n\n{data["message"]}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient or settings.DEFAULT_FROM_EMAIL],
            reply_to=[data['email']],
        )
        try:
            message.send()
        except Exception:  # noqa: BLE001 - el correo es secundario a la página.
            logger.exception('No se pudo enviar el mensaje de contacto')
