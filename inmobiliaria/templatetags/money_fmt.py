from django import template

from inmobiliaria.money_fmt import format_monto_us, format_numero_us

register = template.Library()


@register.filter(name="money_us")
def money_us(value):
    """Formato 22,500.00 (sin símbolo)."""
    if value is None or value == "":
        return ""
    return format_monto_us(value, con_simbolo=False)


@register.filter(name="money_us_symbol")
def money_us_symbol(value):
    """Formato $22,500.00."""
    if value is None or value == "":
        return "—"
    return format_monto_us(value, con_simbolo=True)


@register.filter(name="money_us_int")
def money_us_int(value):
    """Formato 22,500 (sin decimales ni símbolo)."""
    if value is None or value == "":
        return ""
    return format_numero_us(value, decimales=0)
