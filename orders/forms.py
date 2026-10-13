"""Formulario de checkout."""
import re

from django import forms

from .regions import REGION_CHOICES, is_valid_location

#: Acepta formatos chilenos habituales: +56912345678, 912345678, 22 123 4567.
PHONE_RE = re.compile(r'^\+?56?\s?9?\d{7,9}$|^\+?\d{8,15}$')


class CheckoutForm(forms.Form):
    """Datos del comprador y de despacho.

    La validación es del lado del servidor; el JavaScript solo mejora la
    experiencia (filtra comunas según la región) y nunca sustituye a esta
    comprobación.
    """

    first_name = forms.CharField(
        label='Nombre', max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Ana', 'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        label='Apellido', max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Soto', 'autocomplete': 'family-name',
        }),
    )
    email = forms.EmailField(
        label='Email', max_length=150,
        help_text='Aquí enviaremos la confirmación de tu compra.',
        widget=forms.EmailInput(attrs={
            'class': 'form-input', 'placeholder': 'ana@email.cl', 'autocomplete': 'email',
        }),
    )
    phone = forms.CharField(
        label='Teléfono', max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': '+56 9 1234 5678', 'autocomplete': 'tel',
        }),
    )

    region = forms.ChoiceField(
        label='Región', choices=REGION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_region'}),
    )
    commune = forms.CharField(
        label='Comuna', max_length=100,
        widget=forms.Select(attrs={'class': 'form-input', 'id': 'id_commune'}),
    )
    address = forms.CharField(
        label='Dirección', max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Av. Providencia',
            'autocomplete': 'address-line1',
        }),
    )
    address_number = forms.CharField(
        label='Número', max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '1234'}),
    )
    extra = forms.CharField(
        label='Información adicional', max_length=200, required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 'placeholder': 'Depto 42, timbre 3 (opcional)',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El <select> de comuna lo puebla checkout.js según la región. Se le
        # pasa el valor ya elegido para reponerlo si el formulario vuelve con
        # errores de validación.
        selected = self.data.get('commune') or self.initial.get('commune') or ''
        self.fields['commune'].widget.attrs['data-selected'] = selected

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        compact = re.sub(r'[\s\-()]', '', phone)
        if not PHONE_RE.match(compact):
            raise forms.ValidationError(
                'Ingresa un teléfono válido, por ejemplo +56 9 1234 5678.'
            )
        return compact

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean(self):
        cleaned = super().clean()
        region = cleaned.get('region')
        commune = cleaned.get('commune')

        # La comuna llega desde un <select> poblado por JavaScript: hay que
        # verificar en el servidor que corresponde a la región elegida.
        if region and commune and not is_valid_location(region, commune):
            self.add_error(
                'commune',
                'Selecciona una comuna válida para la región indicada.',
            )
        return cleaned
