"""Formularios compartidos del sitio público (login, etc.)."""

from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Campos con clases para estilos de la pantalla de ingreso."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        common = {
            "class": "login-input",
            "autocomplete": "username",
            "spellcheck": "false",
        }
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs.update({**common, "autocomplete": "username"})
        self.fields["password"].label = "Contraseña"
        self.fields["password"].widget.attrs.update(
            {
                "class": "login-input",
                "autocomplete": "current-password",
            }
        )
