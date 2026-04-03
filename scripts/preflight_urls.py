"""Comprueba que /ping/ resuelve (proceso limpio, sin django.setup previo en app.py)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from django.urls import get_resolver, resolve  # noqa: E402

n = len(get_resolver().url_patterns)
if n < 8:
    print(f"ERROR: se esperaban al menos 8 rutas raíz, hay {n}", file=sys.stderr)
    sys.exit(1)
m = resolve("/ping/")
if m.url_name != "ping":
    print(f"ERROR: /ping/ debe nombrarse 'ping', obtuve {m.url_name!r}", file=sys.stderr)
    sys.exit(1)
print(f"Preflight OK: {n} rutas, /ping/ -> {m.url_name}")
