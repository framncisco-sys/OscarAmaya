from django import template

register = template.Library()


@register.inclusion_tag("includes/pbr_icon.html")
def pbr_icon(name, size="md", class_name=""):
    return {
        "name": (name or "").strip().lower(),
        "size": size,
        "class_name": class_name,
    }
