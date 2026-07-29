from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from inmobiliaria.phone_sv import aplicar_attrs_telefono, limpiar_telefono_formulario

from .models import PerfilUsuario

User = get_user_model()

_ROL_HELP = (
    "Administrador / Gerencia: acceso completo en su empresa. "
    "Ventas / comercial: solo el flujo de venta (formato, contrato, pagos). "
    "Tras crear un vendedor, vincúlelo en el catálogo Vendedores."
)

_EMPRESA_HELP = (
    "Solo administradores pueden tener «Ambas empresas». "
    "Gerencia y el resto deben quedar asignados a Bienes Raíces o Desarrollos."
)


def _choices_empresa_para(*, es_admin_editor: bool, forzar_slug: str | None = None):
    if forzar_slug:
        return [
            (c.value, c.label)
            for c in PerfilUsuario.Empresa
            if c.value == forzar_slug
        ]
    if es_admin_editor:
        return list(PerfilUsuario.Empresa.choices)
    return [
        (c.value, c.label)
        for c in PerfilUsuario.Empresa
        if c.value != PerfilUsuario.Empresa.AMBAS
    ]


def validar_rol_empresa(rol: str, empresa: str) -> None:
    if rol == PerfilUsuario.Rol.ADMINISTRADOR:
        if empresa != PerfilUsuario.Empresa.AMBAS:
            raise ValidationError(
                {
                    "empresa": "El administrador de sistema debe tener acceso a ambas empresas.",
                }
            )
        return
    if empresa == PerfilUsuario.Empresa.AMBAS:
        raise ValidationError(
            {
                "empresa": "Solo el rol Administrador puede tener «Ambas empresas».",
            }
        )


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
        label="Correo",
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
        label="Rol",
        choices=PerfilUsuario.Rol.choices,
        help_text=_ROL_HELP,
    )
    empresa = forms.ChoiceField(
        label="Empresa",
        choices=PerfilUsuario.Empresa.choices,
        help_text=_EMPRESA_HELP,
    )
    telefono = forms.CharField(label="Teléfono", max_length=40, required=False)
    cuenta_activa = forms.BooleanField(
        label="Cuenta activa (puede iniciar sesión y usar la app)",
        initial=True,
        required=False,
    )
    acceso_interno = forms.BooleanField(
        label="Acceso técnico al panel interno (/interno/)",
        initial=False,
        required=False,
        help_text="Solo para personal de sistemas. Los vendedores y la gerencia de oficina no lo necesitan.",
    )

    def __init__(
        self,
        *args,
        mostrar_acceso_interno: bool = False,
        es_admin_editor: bool = False,
        forzar_empresa: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if not mostrar_acceso_interno:
            self.fields.pop("acceso_interno", None)
        self.fields["empresa"].choices = _choices_empresa_para(
            es_admin_editor=es_admin_editor,
            forzar_slug=forzar_empresa,
        )
        if forzar_empresa:
            self.fields["empresa"].initial = forzar_empresa
            self.fields["empresa"].widget.attrs["readonly"] = True
        if not es_admin_editor:
            # Gerencia no crea administradores de sistema.
            self.fields["rol"].choices = [
                (c.value, c.label)
                for c in PerfilUsuario.Rol
                if c.value != PerfilUsuario.Rol.ADMINISTRADOR
            ]
        aplicar_attrs_telefono(self.fields.get("telefono"))

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))

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
        rol = data.get("rol")
        empresa = data.get("empresa")
        if rol and empresa:
            validar_rol_empresa(rol, empresa)
        return data


class UsuarioAppEditarForm(forms.Form):
    email = forms.EmailField(required=False, label="Correo")
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
        label="Rol",
        choices=PerfilUsuario.Rol.choices,
        help_text=_ROL_HELP,
    )
    empresa = forms.ChoiceField(
        label="Empresa",
        choices=PerfilUsuario.Empresa.choices,
        help_text=_EMPRESA_HELP,
    )
    telefono = forms.CharField(label="Teléfono", max_length=40, required=False)
    notas = forms.CharField(label="Notas internas", widget=forms.Textarea, required=False)
    cuenta_activa = forms.BooleanField(
        label="Cuenta activa (puede iniciar sesión y usar la app)",
        required=False,
    )
    acceso_interno = forms.BooleanField(
        label="Acceso técnico al panel interno (/interno/)",
        required=False,
        help_text="Solo para personal de sistemas. Los vendedores y la gerencia de oficina no lo necesitan.",
    )

    def __init__(
        self,
        *args,
        mostrar_acceso_interno: bool = False,
        es_admin_editor: bool = False,
        forzar_empresa: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if not mostrar_acceso_interno:
            self.fields.pop("acceso_interno", None)
        self.fields["empresa"].choices = _choices_empresa_para(
            es_admin_editor=es_admin_editor,
            forzar_slug=forzar_empresa,
        )
        if forzar_empresa:
            self.fields["empresa"].initial = forzar_empresa
        if not es_admin_editor:
            self.fields["rol"].choices = [
                (c.value, c.label)
                for c in PerfilUsuario.Rol
                if c.value != PerfilUsuario.Rol.ADMINISTRADOR
            ]
        aplicar_attrs_telefono(self.fields.get("telefono"))

    def clean_telefono(self):
        return limpiar_telefono_formulario(self.cleaned_data.get("telefono"))

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
        rol = data.get("rol")
        empresa = data.get("empresa")
        if rol and empresa:
            validar_rol_empresa(rol, empresa)
        return data
