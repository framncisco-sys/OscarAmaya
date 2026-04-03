"""
Django 6: django.core.signing.JSONSerializer usa json.dumps sin cls.
Cualquier objeto con datetime en firmas/sesiones rompe con TypeError.

Este parche aplica DjangoJSONEncoder al serializador por defecto de signing
y actualiza la referencia en django.contrib.sessions.serializers.
"""

from __future__ import annotations

import json

from django.core.serializers.json import DjangoJSONEncoder


def apply() -> None:
    from django.core import signing
    import django.contrib.sessions.serializers as session_serializers

    class _FixedSigningJSONSerializer(signing.JSONSerializer):
        def dumps(self, obj):
            return json.dumps(
                obj,
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
            ).encode("latin-1")

    signing.JSONSerializer = _FixedSigningJSONSerializer
    session_serializers.JSONSerializer = signing.JSONSerializer
