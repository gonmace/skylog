# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Desarrollo local
```bash
make install      # pip install -r requirements-dev.txt + tailwind install
make dev-up       # levanta PostgreSQL + n8n en Docker (docker-compose.dev.yml)
make dev          # migrate + tailwind start (background) + runserver
make dev-down     # detiene los contenedores de desarrollo
make dev-logs     # logs de los contenedores de desarrollo
```

En desarrollo, Tailwind y Django se ejecutan en terminales separadas:
```bash
# Terminal 1
python manage.py tailwind start

# Terminal 2
python manage.py runserver
```

### Django
```bash
make migrate      # python manage.py migrate
make migrations   # python manage.py makemigrations
make superuser    # python manage.py createsuperuser
make collect      # collectstatic
make shell        # python manage.py shell
```

### n8n
```bash
make n8n-export   # exporta workflows de n8n dev a n8n/workflows/ (para commitear)
```

### Producción
```bash
make deploy       # bash deploy.sh (VPS)
make logs         # docker compose logs -f django
make down         # docker compose down
```

On Windows, `NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'` is set in settings.py inside the `if DEBUG:` block.

## Architecture

Single `core/settings.py` — no separate dev/prod files. Behavior adapts via environment variables:
- `DEBUG=True` → SQLite, console email, Tailwind + browser-reload enabled
- `POSTGRES_DB` defined → PostgreSQL
- `EMAIL_HOST` defined → SMTP backend
- `DEBUG=False` → HSTS, secure CSRF, no dev tools

**Tailwind setup** (`django-tailwind` + Tailwind CSS v4 + DaisyUI v5):
- Source CSS: `theme/static_src/src/styles.css`
- Output CSS: `theme/static/css/dist/styles.css` (served by Django's staticfiles from the `theme` app)
- `{% load tailwind_tags %}` + `{% tailwind_css %}` in `templates/base.html` loads the CSS
- `@source not "../static"` prevents a recompile loop from the output file
- When adding new Django apps, add `@source "../../../<app_name>"` to `styles.css` so Tailwind scans its templates

**Static files:** Whitenoise serves static files in production (configured in `STORAGES`). `STATICFILES_DIRS` points to the root `static/` folder.

**Security:** django-axes (brute-force lockout after 5 failures, 1h cooldown), django-csp (Content Security Policy headers), HSTS in production.

**Admin URL** is randomized via `ADMIN_URL` env var (default: `admin/`). Exposed in `robots.txt` via template context.

**n8n (opcional):**
- n8n es opcional — se activa definiendo `N8N_DOMAIN` en `.env`. Si no está definido, no se levanta ningún contenedor n8n.
- Dev: `docker-compose.dev.yml` levanta PostgreSQL (puerto `POSTGRES_PORT` expuesto en el host) + n8n en `http://localhost:5678`
- Prod: n8n usa Docker Compose profile `n8n` — `deploy.sh` lo activa automáticamente si `N8N_DOMAIN` está definido en `.env`
- Imagen custom con Python 3.12 (`docker/n8n.Dockerfile`), subdominio propio, volumen bind mount `./volumes/n8n`
- n8n usa la misma instancia de PostgreSQL con una base de datos separada (`n8n`). `docker/init-db.sql` la crea solo al inicializar el contenedor postgres por primera vez; en una BD ya existente hay que crearla a mano (`CREATE DATABASE n8n;`)
- Los workflows se exportan con `make n8n-export` a `n8n/workflows/`. En producción **no** se importan solos: tras levantar n8n, correr `make n8n-import` (`n8n import:workflow --separate`) y luego `docker compose restart n8n` para activarlos. Las URLs/token con que el workflow llama a Django se leen via `$env` (`DJANGO_INTERNAL_URL`, `INTERNAL_API_TOKEN`), definidas en el servicio n8n del compose
- `N8N_ENCRYPTION_KEY` debe mantenerse constante en cada entorno — cambiarla invalida las credenciales guardadas

**Production:** Docker Compose + Gunicorn (`entrypoint.sh`) + Nginx. Templates: `nginx.conf` (Django, siempre) + `nginx-n8n.conf` (n8n, solo si `N8N_DOMAIN` está definido), concatenados por `nginx-deploy.sh`. CSS compilado en Dockerfile multi-stage (Node → Python).

## CSS / Styling rules

### Dónde viven los estilos
- **Todos los estilos reutilizables van en `theme/static_src/src/styles.css`** dentro de `@layer components`.
- Los templates **no deben tener `<style>` blocks** salvo para clases generadas dinámicamente por JS en tiempo de ejecución (ej. clases que `renderRow()` inyecta en el DOM y que Tailwind no puede escanear en build-time). Esas clases JS-generated deben estar explícitamente comentadas en el `<style>` con `/* JS-generated: usado por renderRow() */`.
- Nunca usar `style="..."` inline salvo para mostrar/ocultar elementos que JS maneja con `element.style.display` — en ese caso usar `style="display:none"` y NO `class="hidden"` (Tailwind genera `display:none !important` que JS no puede sobreescribir).

### Paleta de tokens
- Los colores de acento se referencian siempre como tokens DaisyUI (`var(--color-success)`, `var(--color-info)`, etc.) o via variables `--cp-*` que ya apuntan a esos tokens.
- **No usar colores hex hardcodeados** en estilos de componentes nuevos — usar los tokens del tema.
- `--cp-green` = `var(--color-success)`, `--cp-blue` = `var(--color-info)`, `--cp-red` = `var(--color-primary)`, `--cp-orange` = `var(--color-error)`, `--cp-yellow` = `var(--color-warning)`, `--cp-purple` = `var(--color-accent)`.

### Patrón de botones translúcidos (`.btn-tinted`)
El patrón estándar para botones ghost con fondo translúcido persistente es la clase `.btn-tinted` definida en `styles.css`:

```html
<!-- El color lo controla la clase text-* -->
<button class="btn-tinted btn-sm gap-1.5 text-success">Exportar Excel</button>
<button class="btn-tinted btn-sm gap-1.5 text-error">Exportar Certificado</button>
<button class="btn-tinted btn-sm gap-1.5 text-base-content/60">Imprimir</button>
<button class="btn-tinted gap-2 text-info">Ver Registro</button>
```

- Fondo: `color-mix(currentColor 12%, transparent)` en reposo → 22% en hover
- Borde: `color-mix(currentColor 28%, transparent)` en reposo → 45% en hover
- **No usar** `btn btn-ghost border border-{color}/30 text-{color} hover:bg-{color}/15` — eso era el patrón anterior, reemplazado por `.btn-tinted`.

### Patrón de botones ghost con tint en hover (`.btn-ghost-tinted`)
Para botones sin fondo ni borde por defecto que revelan el tint solo al hacer hover (ej. botón cerrar sesión):

```html
<button class="btn-ghost-tinted btn-square btn-sm text-error">…</button>
<button class="btn-ghost-tinted btn-sm text-error">Salir</button>
```

- Default: completamente transparente (sin fondo, sin borde)
- Hover: fondo 15% + borde 30% del color actual (`currentColor`)
- Usar cuando el botón es secundario/destructivo y no debe llamar la atención en reposo

### Patrón de botones de navegación (`.btn-nav`)
Para flechas de calendario y controles de navegación donde el hover es solo un contorno fino sin fondo:

```html
<button class="btn-nav btn-square btn-sm">…</button>
<button class="btn-nav btn-square btn-xs">…</button>
```

- Default: completamente transparente (sin fondo, sin borde)
- Hover: solo borde fino `base-content/18%`, sin fondo
- Usar para flechas prev/next de calendarios y controles de paginación

### Visibilidad controlada por JS
Cuando un elemento es ocultado/mostrado por JS con `element.style.display`:
```html
<!-- CORRECTO -->
<div id="mi-div" style="display:none" class="min-h-screen bg-base-200 ...">

<!-- INCORRECTO — Tailwind genera display:none !important, JS no puede sobreescribir -->
<div id="mi-div" class="hidden min-h-screen bg-base-200 ...">
```
