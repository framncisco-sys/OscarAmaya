from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import PerfilUsuario

User = get_user_model()


class UsuarioAppCrearForm(forms.Form):
    username = forms.CharField(
        label="Usuario (inicio de sesión)",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "data-lpignore": "true",
                "data-1p-ignore": "true",
            },
        ),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    rol = forms.ChoiceField(
        label="Rol en la aplicación",
        choices=PerfilUsuario.Rol.choices,
    )
    telefono = forms.CharField(max_length=40, required=False)
    activo_en_app = forms.BooleanField(
        label="Activo en gestión web (/app/)",
        initial=True,
        required=False,
    )
    is_staff = forms.BooleanField(
        label="Puede acceder al sitio de administración Django (/interno/)",
        initial=True,
        required=False,
        help_text="Solo marque si necesita el panel admin clásico.",
    )

    def clean_username(self):
        u = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=u).exists():
            raise ValidationError("Ya existe un usuario con ese nombre.")
        return u

    def clean(self):
        data = super().clean()
        p1 = data.get("password1")
        p2 = data.get("password2")
        if p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")
        if p1:
            validate_password(p1)
        return data


class UsuarioAppEditarForm(forms.Form):
    email = forms.EmailField(required=False)
    first_name = forms.CharField(label="Nombre", max_length=150, required=False)
    last_name = forms.CharField(label="Apellidos", max_length=150, required=False)
    password1 = forms.CharField(
        label="Nueva contraseña (opcional)",
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "Dejar vacío para no cambiar"},
        ),
        required=False,
    )
    password2 = forms.CharField(
        label="Repetir nueva contraseña",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=False,
    )
    rol = forms.ChoiceField(
        label="Rol en la aplicación",
        choices=PerfilUsuario.Rol.choices,
        help_text="Se guarda el rol que elija. Si el usuario sigue marcado como superusuario de Django, conserva acceso total en /interno/ aunque aquí figure otro rol.",
    )
    telefono = forms.CharField(max_length=40, required=False)
    notas = forms.CharField(widget=forms.Textarea, required=False)
    activo_en_app = forms.BooleanField(
        label="Activo en gestión web (/app/)",
        required=False,
    )
    is_active = forms.BooleanField(label="Usuario activo (Django)", required=False)
    is_staff = forms.BooleanField(
        label="Staff Django (/interno/)",
        required=False,
    )

    def clean(self):
        data = super().clean()
        # Evitar que el autofill del navegador rellene solo uno y invalide todo el guardado.
        p1 = (data.get("password1") or "").strip()
        p2 = (data.get("password2") or "").strip()
        data["password1"] = p1
        data["password2"] = p2
        if p1 or p2:
            if p1 != p2:
                raise ValidationError("Las contraseñas nuevas no coinciden.")
            validate_password(p1)
        return data
