"""
Arranque del servidor de desarrollo Django.

El servidor se ejecuta en un proceso hijo (manage.py runserver) para no mezclar
django.setup() de este script con el proceso del runserver (evita estados raros del URLconf).

Uso: python app.py
     python app.py 8001
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

if __name__ == "__main__":
    # Preferimos el Python del virtualenv aunque no esté activado.
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_python) if venv_python.is_file() else sys.executable

    # Si ya hay algo escuchando en el puerto, mátalo (evita servidores viejos).
    port_arg = "8000"
    port = "8000"
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = sys.argv[1]
        port_arg = port
    addr = f"127.0.0.1:{port}"

    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"$p={port_arg};"
                "$l=netstat -ano | Select-String (\":$p\\s\");"
                "foreach($x in $l){"
                " if($x.Line -match 'LISTENING\\s+(\\d+)\\s*$'){"
                "  $pid=[int]$Matches[1];"
                "  try{ taskkill /PID $pid /F | Out-Null } catch {}"
                " }"
                "}",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

    pre = subprocess.run(
        [py, str(ROOT / "scripts" / "preflight_urls.py")],
        cwd=ROOT,
    )
    if pre.returncode != 0:
        if not venv_python.is_file():
            print(
                "ERROR: no se encontró .venv. Activa el entorno o crea el virtualenv antes de ejecutar.",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"Iniciando servidor en http://{addr}/")
    print(f"- Panel Django Admin: http://{addr}/interno/")
    print(
        "- Diagnóstico: cada respuesta lleva cabeceras X-PBR-URLconf-Routes y X-PBR-URLconf-File "
        "(debe ser 8 rutas y la ruta a backend/urls.py de este proyecto)."
    )
    print(f"- Cabeceras diagnóstico: curl.exe -s -D - -o NUL http://{addr}/ping/")
    print(f"  (o: .\\scripts\\ping_headers.ps1) — en PowerShell, sin -SkipHttpErrorCheck, 404 deja $r vacío.")
    # Sin --noreload: al guardar cambios en plantillas o .py el servidor recarga (desarrollo).
    child = subprocess.Popen(
        [py, str(ROOT / "manage.py"), "runserver", addr],
        cwd=ROOT,
    )
    print(f"- PID runserver: {child.pid}")
    try:
        raise SystemExit(child.wait())
    except KeyboardInterrupt:
        # En Windows, Ctrl+Break/Ctrl+C puede interrumpir el padre y dejar el hijo vivo.
        # Terminamos explícitamente el runserver para evitar puertos ocupados con código viejo.
        try:
            child.terminate()
        except Exception:
            pass
        try:
            child.wait(timeout=5)
        except Exception:
            try:
                child.kill()
            except Exception:
                pass
        raise SystemExit(130)
