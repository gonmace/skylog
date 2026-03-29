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
- Dev: `docker-compose.dev.yml` levanta PostgreSQL (puerto `POSTGRES_HOST_PORT` expuesto) + n8n en `http://localhost:5678`
- Prod: n8n usa Docker Compose profile `n8n` — `deploy.sh` lo activa automáticamente si `N8N_DOMAIN` está definido en `.env`
- Imagen custom con Python 3.12 (`docker/n8n.Dockerfile`), subdominio propio, volumen bind mount `./volumes/n8n`
- n8n usa la misma instancia de PostgreSQL con una base de datos separada (`n8n`), creada por `docker/init-db.sql`
- Los workflows se exportan con `make n8n-export` a `n8n/workflows/` y se importan automáticamente en producción al arrancar el contenedor
- `N8N_ENCRYPTION_KEY` debe mantenerse constante en cada entorno — cambiarla invalida las credenciales guardadas

**Production:** Docker Compose + Gunicorn (`entrypoint.sh`) + Nginx. Templates: `nginx.conf` (Django, siempre) + `nginx-n8n.conf` (n8n, solo si `N8N_DOMAIN` está definido), concatenados por `nginx-deploy.sh`. CSS compilado en Dockerfile multi-stage (Node → Python).
