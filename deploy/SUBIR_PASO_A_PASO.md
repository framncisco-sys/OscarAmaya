# Subir el proyecto a DigitalOcean — paso a paso

No puedo entrar a tu cuenta de DigitalOcean ni a GitHub por ti; sigue esta lista en orden. Tu carpeta del proyecto es `c:\PAREDES BIENES RAICES` y el archivo **`.env` no debe subirse a internet** (ya está en `.gitignore`).

### Si PowerShell dice que no reconoce `git`

Git suele estar en `C:\Program Files\Git\bin\git.exe` pero **no está en el PATH**. Elija una opción:

**A) Solo esta ventana de PowerShell:**

```powershell
$env:Path = "C:\Program Files\Git\bin;" + $env:Path
git --version
```

**B) Para siempre (recomendado):**  
*Configuración → Sistema → Acerca de → Configuración avanzada del sistema → Variables de entorno → Path (Usuario o Sistema) → Nuevo →* pegue `C:\Program Files\Git\bin` → Aceptar. Cierre y abra PowerShell.

También puede usar la ruta completa sin cambiar PATH:

```powershell
& "C:\Program Files\Git\bin\git.exe" status
```

---

## Paso 1 — Instalar Git en Windows

1. Descarga: [https://git-scm.com/download/win](https://git-scm.com/download/win)
2. Instala con las opciones por defecto (incluye **Git Bash**).
3. **Cierra y vuelve a abrir** PowerShell o Cursor para que reconozca el comando `git`.
4. Comprueba en una terminal nueva:

   ```powershell
   git --version
   ```

Si prefieres interfaz gráfica, puedes usar **GitHub Desktop** ([desktop.github.com](https://desktop.github.com)): crea el repositorio, añade la carpeta del proyecto y publica; igual debes revisar que `.env` no se suba (GitHub Desktop respeta `.gitignore`).

---

## Paso 2 — Crear repositorio vacío en GitHub

1. Entra a [https://github.com](https://github.com) e inicia sesión.
2. **New repository** (nuevo repositorio).
3. Nombre sugerido: `paredes-bienes-raices`.
4. **Público** o **Privado** (privado recomendado si hay datos sensibles en el código).
5. **No marques** “Add a README” si vas a empujar código que ya tienes en la PC (evita conflictos).
6. Crea el repositorio y copia la URL que te muestra, por ejemplo:

   `https://github.com/TU_USUARIO/paredes-bienes-raices.git`

---

## Paso 3 — Subir el código desde tu PC

Abre **PowerShell** en la carpeta del proyecto:

```powershell
cd "c:\PAREDES BIENES RAICES"
git init
git branch -M main
git add .
git status
```

En `git status` **no** debe aparecer `.env`. Si aparece, no continúes: díganos y corrija `.gitignore`.

```powershell
git commit -m "Proyecto Django Paredes Bienes Raices"
git remote add origin https://github.com/TU_USUARIO/paredes-bienes-raices.git
git push -u origin main
```

GitHub pedirá usuario y contraseña; si usa autenticación moderna, necesita un **Personal Access Token** en lugar de la contraseña de la cuenta ([documentación GitHub](https://docs.github.com/en/authentication)).

---

## Paso 4 — Crear la aplicación en DigitalOcean App Platform

1. Entra a [https://cloud.digitalocean.com](https://cloud.digitalocean.com) → **Apps** → **Create** → **Apps**.
2. Conecta **GitHub** (autoriza a DigitalOcean).
3. Elige el repositorio `paredes-bienes-raices` y la rama `main`.
4. DigitalOcean detectará un proyecto Python. Revise:

   - **Source directory**: `/` (raíz, donde está `manage.py`).
   - **Resource type**: **Web Service**.

5. **Build command** (sustituya si el panel ya lo rellena mal):

   ```bash
   pip install -r requirements.txt && python manage.py collectstatic --noinput
   ```

6. **Run command** (o deje que use el `Procfile`):

   ```bash
   gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120
   ```

7. **HTTP port**: suele ser **8080** si el comando usa `$PORT` (App Platform inyecta `PORT`).

---

## Paso 5 — Base de datos PostgreSQL

Si **ya tiene** el cluster de PostgreSQL en DigitalOcean:

1. En la misma App o en **Resources**, añada la base como recurso vinculado **o**
2. En **Settings → App-Level Environment Variables** (o las variables del componente **web**) defina **a mano**:

   | Variable | Valor (ejemplo; use los suyos del panel de la BD) |
   |----------|-----------------------------------------------------|
   | `POSTGRES_DB` | `defaultdb` |
   | `POSTGRES_USER` | `doadmin` |
   | `POSTGRES_PASSWORD` | *(pegar desde el panel; marque como **SECRET**)* |
   | `POSTGRES_HOST` | host que termina en `.db.ondigitalocean.com` |
   | `POSTGRES_PORT` | `25060` |
   | `POSTGRES_SSLMODE` | `require` |

3. En el panel de la base de datos → **Trusted sources**: permita el tráfico desde **App Platform** (a veces aparece como opción al vincular la app) o añada el rango que indique DigitalOcean.

---

## Paso 6 — Variables de Django (producción)

En el mismo componente **Web Service** → **Environment Variables**:

| Variable | Valor |
|----------|--------|
| `DEBUG` | `False` |
| `DJANGO_SETTINGS_MODULE` | `backend.settings` |
| `SECRET_KEY` | Una clave larga aleatoria (tipo **SECRET**) — puede generarla en la PC: `python -c "import secrets; print(secrets.token_urlsafe(56))"` |
| `DJANGO_ALLOWED_HOSTS` | Tras el primer deploy verá una URL; ejemplo: `tu-app-xxxxx.ondigitalocean.app` o `.ondigitalocean.app` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://tu-app-xxxxx.ondigitalocean.app` (exactamente con `https://`, sin barra final) |
| `PUBLIC_BASE_URL` | La misma URL `https://...` |

Guarde y vuelva a desplegar si cambia el hostname.

---

## Paso 7 — Primer deploy y comandos en consola

1. Pulse **Deploy** / **Create resources** y espere a que termine el build.
2. Si el build falla, abra **Runtime Logs** y copie el error.
3. Cuando la app esté **Running**, abra **Console** (consola del componente web) y ejecute:

   ```bash
   python manage.py migrate --noinput
   python manage.py createsuperuser
   ```

4. Abra en el navegador la URL HTTPS que muestra la App.

---

## Errores frecuentes

- **CSRF / 403 al iniciar sesión**: `DJANGO_CSRF_TRUSTED_ORIGINS` debe coincidir **exactamente** con la URL pública (https).
- **400 Bad Request / DisallowedHost**: añada el hostname en `DJANGO_ALLOWED_HOSTS`.
- **Error de conexión a PostgreSQL**: `POSTGRES_SSLMODE=require`, puerto `25060`, y **Trusted sources** de la BD deben permitir la App.
- **Archivos estáticos en blanco**: el **build** debe incluir `collectstatic` (ver Paso 4).

---

## Resumen

| Dónde | Qué |
|--------|-----|
| Su PC | Git + `git push` a GitHub (sin `.env`) |
| GitHub | Código del proyecto |
| DigitalOcean App | Web service + variables + PostgreSQL |
| Consola DO | `migrate` + `createsuperuser` |

Si en el **Paso 3** `git` sigue sin reconocerse, instale Git y use una terminal nueva. Si quiere, pegue aquí el mensaje de error del **build** o del **deploy** en DigitalOcean (sin contraseñas) y lo revisamos.
