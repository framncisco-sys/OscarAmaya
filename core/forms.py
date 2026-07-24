"""Formularios compartidos del sitio público (login, etc.)."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class LoginForm(AuthenticationForm):
    """Ingreso al sistema con validaciones y mensajes en español."""

    error_messages = {
        "invalid_login": (
            "Usuario o contraseña incorrectos. Verifique sus datos e intente de nuevo."
        ),
        "inactive": "Esta cuenta está desactivada. Contacte al administrador del sistema.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs.update(
            {
                "class": "login-input",
                "autocomplete": "username",
                "spellcheck": "false",
                "required": "required",
                "minlength": "2",
                "maxlength": "150",
                "placeholder": "Nombre de usuario",
                "aria-required": "true",
            }
        )
        self.fields["password"].label = "Contraseña"
        self.fields["password"].widget.attrs.update(
            {
                "class": "login-input login-input--password",
                "autocomplete": "current-password",
                "required": "required",
                "minlength": "1",
                "placeholder": "Su contraseña",
                "aria-required": "true",
            }
        )

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        if isinstance(username, str):
            username = username.strip()
        if not username:
            raise ValidationError("Ingrese su nombre de usuario.")
        if len(username) < 2:
            raise ValidationError("El usuario debe tener al menos 2 caracteres.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not password:
            raise ValidationError("Ingrese su contraseña.")
        return password

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise ValidationError(
                self.error_messages["inactive"],
                code="inactive",
            )
