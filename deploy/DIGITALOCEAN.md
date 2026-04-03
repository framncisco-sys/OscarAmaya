# Despliegue en DigitalOcean (Paredes Bienes Raíces)

Plantilla lista para pegar variables en el panel: **`deploy/COPIAR_A_DIGITALOCEAN.txt`**.

Guía para probar la aplicación Django en **DigitalOcean**. Hay dos caminos habituales: **App Platform** (menos mantenimiento) o **Droplet** (VPS con más control).

## Requisitos previos

- Cuenta en [DigitalOcean](https://www.digitalocean.com/).
- Código en **GitHub/GitLab** (App Platform) o acceso SSH al servidor (Droplet).
- **PostgreSQL**: base administrada (recomendado) o PostgreSQL instalado en el Droplet.
- Archivo **`.env`** en el servidor (o variables en el panel de DO) **nunca** commiteado al repositorio.

## Variables de entorno imprescindibles (producción)

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Clave larga y aleatoria (no use la de ejemplo del código). |
| `DEBUG` | `False` |
| `DJANGO_ALLOWED_HOSTS` | Dominios o IPs separados por coma, sin espacios. Incluya el hostname de App Platform, ej. `tu-app.ondigitalocean.app` o `.ondigitalocean.app` para todos los subdominios. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | URLs completas con `https://`, separadas por coma. Ej. `https://tu-app.ondigitalocean.app` |
| `DATABASE_URL` | Opcional: DigitalOcean suele inyectarla al vincular PostgreSQL; si está definida, **prevalece** sobre `POSTGRES_*`. |
| `PGHOST` / `PG*` | Si el entorno define `PGHOST` (estilo libpq), el proyecto puede usar `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGPORT` sin duplicar `POSTGRES_*`. |
| `POSTGRES_*` | Si no hay `DATABASE_URL` ni `PGHOST`: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` (en bases administradas el puerto suele ser **25060** y hace falta **SSL**; vea nota más abajo). |
| `PUBLIC_BASE_URL` | URL pública `https://...` (recibos y enlaces). |
| `DJANGO_USE_S3_MEDIA` + `AWS_*` | Opcional y **recomendado** en App Platform: guardar PDFs/planos en **Spaces** (S3) para que no se pierdan al redeploy. Vea `.env.example` y `deploy/COPIAR_A_DIGITALOCEAN.txt`. |

Copie `.env.example` a `.env` y complételo. En DigitalOcean use la pestaña **Environment** del componente o los **Secrets**.

### Si el login falla con `connection refused` a `127.0.0.1:5432`

Eso indica que el **Web Service** no tiene `DATABASE_URL` ni `POSTGRES_HOST` remotos: Django usa los valores por defecto (`localhost`). Las variables deben estar en el **mismo componente** que ejecuta Gunicorn (Web Service), no solo en el recurso Database.

1. **Databases** (menú lateral) → su clúster PostgreSQL → **Connection details** → copie la URI o host, puerto, usuario, contraseña y base.
2. **Apps** → su app → **Settings** → **Components** → su **Web Service** → **Edit** → **Environment Variables**.
3. Añada **`DATABASE_URL`** = cadena `postgresql://...?sslmode=require` **o** las variables sueltas `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_SSLMODE=require`.
4. **Save** y **Deploy**. Luego en la consola del Web Service: `python manage.py migrate --noinput`.

Comprobación rápida (JSON): `https://su-app.ondigitalocean.app/ping/?db=1` con `DEBUG=True` o con la variable `PBR_ALLOW_DB_PING=1` (sin exponer contraseñas).

### PostgreSQL administrado (SSL)

En DigitalOcean PostgreSQL suele hacer falta:

```env
POSTGRES_SSLMODE=require
```

Ya está soportado en `backend/settings.py` vía variable de entorno.

## Validación local (antes de desplegar)

El login falla en App Platform cuando Django sigue usando **host `localhost`** para PostgreSQL: en el contenedor **no** hay servidor PostgreSQL local; hace falta la misma configuración que en su `.env` de desarrollo, pero definida en el **Web Service** del panel.

1. **Comando recomendado** (exige BD remota como en DigitalOcean):

   ```bash
   python manage.py validate_digitalocean --as-app-platform
   ```

   Si responde `[OK]`, la configuración cargada por Django no apunta a localhost. Si responde `[FALLO]`, añada `DATABASE_URL` o `POSTGRES_*` al Web Service antes de desplegar.

2. **Probar conexión real a PostgreSQL** (opcional):

   ```bash
   python manage.py validate_digitalocean --as-app-platform --try-connect
   ```

3. **Check de Django** (error `pbr.E001` solo si existe la variable de entorno `PORT`, como Gunicorn en producción):

   ```powershell
   $env:PORT="8080"
   python manage.py check --deploy
   ```

   Con BD en localhost y `PORT` definido, el check falla con un mensaje que describe el mismo problema que en la nube.

## App Platform (recomendado para pruebas)

1. **Create → Apps → GitHub** y elija el repositorio de este proyecto.
2. **Tipo de recurso**: Web Service. **Raíz del proyecto**: la carpeta donde está `manage.py` (si el repo es solo este proyecto, raíz `/`).
3. **Build command** (importante para CSS/JS estáticos):

   ```bash
   pip install -r requirements.txt && python manage.py collectstatic --noinput
   ```

4. **Run command** (o deje que use el `Procfile`):

   ```bash
   gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120
   ```

5. **Base de datos (obligatorio):** en el contenedor **no** hay PostgreSQL en `localhost`. Debe:
   - **Recomendado:** añadir el recurso **Database** y en el **Web Service** → **Environment** definir `DATABASE_URL` con el valor **enlazado** del asistente (p. ej. `${db.DATABASE_URL}`). El valor **no** debe quedar como texto literal sin resolver.
   - **O bien** copiar del panel de la base host, puerto, usuario, contraseña y nombre de BD y definir `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` y `POSTGRES_SSLMODE=require`.

   Si al iniciar sesión aparece `connection refused` a `127.0.0.1:5432`, las variables **no** están llegando al **Web Service** (revise Environment del componente web, no solo de la base).
6. Añada las variables de Django (`SECRET_KEY`, `DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `PUBLIC_BASE_URL`).
7. **Primera migración**: en la consola del componente (Console) o un job de deploy:

   ```bash
   python manage.py migrate --noinput
   ```

8. Cree un superusuario:

   ```bash
   python manage.py createsuperuser
   ```

9. Abra la URL HTTPS que asigne DigitalOcean. Si ve error de **CSRF**, revise que `DJANGO_CSRF_TRUSTED_ORIGINS` coincida exactamente con esa URL (incluido `https://`).

Hay un ejemplo incompleto en `deploy/digitalocean-app-spec.example.yaml` solo como referencia; el asistente visual del panel suele ser más fiable.

## Droplet (Ubuntu)

1. Droplet Ubuntu 22.04/24.04, tamaño mínimo según carga (1 GB RAM puede valer para pruebas con pocos usuarios).
2. Instale Python 3.12+, PostgreSQL cliente/servidor o use base administrada.
3. Clona el repo, cree `venv`, `pip install -r requirements.txt`.
4. Configure **nginx** como proxy reverso hacia Gunicorn y TLS con **Let’s Encrypt** (Certbot).
5. **Systemd** para Gunicorn, por ejemplo:

   ```ini
   [Service]
   WorkingDirectory=/ruta/al/proyecto
   Environment="PATH=/ruta/al/proyecto/.venv/bin"
   ExecStart=/ruta/al/proyecto/.venv/bin/gunicorn backend.wsgi:application --bind unix:/run/gunicorn.sock --workers 3 --timeout 120
   ```

   O `--bind 127.0.0.1:8001` si nginx hace `proxy_pass` a ese puerto.

6. En cada despliegue:

   ```bash
   python manage.py migrate --noinput
   python manage.py collectstatic --noinput
   sudo systemctl restart gunicorn
   ```

## Archivos añadidos en el proyecto

- `Procfile` — comando web para plataformas tipo Heroku/App Platform.
- `runtime.txt` — versión de Python (3.12.x).
- `requirements.txt` — incluye `gunicorn` y `whitenoise`.
- `STATIC_ROOT` + WhiteNoise en `backend/settings.py` cuando `DEBUG=False` **o** cuando existe la variable `PORT` (Gunicorn en App Platform), para servir CSS/JS/imágenes sin depender solo de nginx.
- `core/checks.py` — comprobación `pbr.E001` con `manage.py check --deploy` y `PORT` definido.
- `python manage.py validate_digitalocean` — validación manual antes de desplegar.
- `.gitignore` — carpeta `staticfiles/` generada por `collectstatic`.

## PDF (WeasyPrint)

En Linux, WeasyPrint puede requerir paquetes del sistema (`pango`, `cairo`, etc.). Si en el servidor no se instalan, el proyecto ya usa **xhtml2pdf** como respaldo en código. Para mejor calidad de PDF en el Droplet, instale las dependencias que indica la [documentación de WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation).

## Comprobar localmente con Gunicorn (antes de subir)

```bash
set DEBUG=False
set DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
set DJANGO_USE_WHITENOISE=1
python manage.py collectstatic --noinput
gunicorn backend.wsgi:application --bind 127.0.0.1:8000
```

En PowerShell use `$env:DEBUG="False"` en lugar de `set`.

---

Si indica si usará **App Platform** o **Droplet**, se puede afinar un único archivo de ejemplo (nginx, systemd o spec YAML) para su caso.
