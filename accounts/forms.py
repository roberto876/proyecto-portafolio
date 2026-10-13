"""Formularios de cuenta de usuario."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from orders.regions import REGION_CHOICES, is_valid_location

from .models import UserProfile

INPUT = {'class': 'form-input'}


class RegistrationForm(UserCreationForm):
    """Alta de usuario. Delega el hashing de la contraseña en Django."""

    email = forms.EmailField(
        label='Email', required=True, max_length=150,
        widget=forms.EmailInput(attrs={
            **INPUT, 'placeholder': 'tu@email.cl', 'autocomplete': 'email',
        }),
    )
    first_name = forms.CharField(
        label='Nombre', max_length=100, required=True,
        widget=forms.TextInput(attrs={
            **INPUT, 'placeholder': 'Ana', 'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        label='Apellido', max_length=100, required=True,
        widget=forms.TextInput(attrs={
            **INPUT, 'placeholder': 'Soto', 'autocomplete': 'family-name',
        }),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            **INPUT, 'placeholder': 'anasoto', 'autocomplete': 'username',
        })
        self.fields['password1'].widget.attrs.update({
            **INPUT, 'placeholder': 'Mínimo 10 caracteres',
            'autocomplete': 'new-password',
        })
        self.fields['password2'].widget.attrs.update({
            **INPUT, 'placeholder': 'Repite la contraseña',
            'autocomplete': 'new-password',
        })

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con este email.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """Inicio de sesión con los estilos de la tienda."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            **INPUT, 'placeholder': 'Usuario', 'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            **INPUT, 'placeholder': 'Contraseña', 'autocomplete': 'current-password',
        })


class UserProfileForm(forms.ModelForm):
    """Datos personales y dirección de despacho predeterminada."""

    first_name = forms.CharField(
        label='Nombre', max_length=100, required=False,
        widget=forms.TextInput(attrs=INPUT),
    )
    last_name = forms.CharField(
        label='Apellido', max_length=100, required=False,
        widget=forms.TextInput(attrs=INPUT),
    )
    email = forms.EmailField(
        label='Email', max_length=150, required=True,
        widget=forms.EmailInput(attrs=INPUT),
    )
    region = forms.ChoiceField(
        label='Región', choices=REGION_CHOICES, required=False,
        widget=forms.Select(attrs={**INPUT, 'id': 'id_region'}),
    )

    class Meta:
        model = UserProfile
        fields = ['phone', 'region', 'commune', 'address', 'address_number']
        labels = {
            'phone': 'Teléfono',
            'commune': 'Comuna',
            'address': 'Dirección',
            'address_number': 'Número',
        }
        widgets = {
            'phone': forms.TextInput(attrs={**INPUT, 'placeholder': '+56 9 1234 5678'}),
            'commune': forms.Select(attrs={**INPUT, 'id': 'id_commune'}),
            'address': forms.TextInput(attrs=INPUT),
            'address_number': forms.TextInput(attrs=INPUT),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None and not self.is_bound:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email

        # checkout.js puebla el <select> de comuna según la región; se le pasa
        # el valor ya guardado para que lo reponga.
        selected = self.data.get('commune') or getattr(self.instance, 'commune', '')
        self.fields['commune'].widget.attrs['data-selected'] = selected or ''

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        others = User.objects.filter(email__iexact=email)
        if self.user is not None:
            others = others.exclude(pk=self.user.pk)
        if others.exists():
            raise forms.ValidationError('Ya existe otra cuenta con este email.')
        return email

    def clean(self):
        cleaned = super().clean()
        region = cleaned.get('region')
        commune = cleaned.get('commune')
        # La comuna solo se valida si el usuario completó la dirección.
        if region and commune and not is_valid_location(region, commune):
            self.add_error('commune', 'Esa comuna no pertenece a la región elegida.')
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if self.user is not None:
            self.user.first_name = self.cleaned_data.get('first_name', '')
            self.user.last_name = self.cleaned_data.get('last_name', '')
            self.user.email = self.cleaned_data['email']
            if commit:
                self.user.save(update_fields=['first_name', 'last_name', 'email'])
        return profile
