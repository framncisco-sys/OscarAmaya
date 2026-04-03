"""
Serializador de sesión compatible con JSON que soporta datetime/date/Decimal/UUID.

El JSONSerializer estándar de Django usa json.dumps sin encoder y puede fallar
con tipos no serializables si algo los guarda en request.session.
"""

import json

from django.contrib.sessions.serializers import JSONSerializer as DjangoJSONSessionSerializer
from django.core.serializers.json import DjangoJSONEncoder


class SafeJSONSerializer(DjangoJSONSessionSerializer):
    def dumps(self, obj):
        return json.dumps(obj, cls=DjangoJSONEncoder, separators=(",", ":")).encode("latin-1")
