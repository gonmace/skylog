# Django Skeleton

Esqueleto base para proyectos Django con Tailwind v4 + DaisyUI v5, listo para desarrollo local y despliegue en producción con Docker + PostgreSQL. n8n es opcional.

## Stack

- **Backend:** Django 5.1+, Gunicorn
- **Base de datos:** SQLite (dev local) / PostgreSQL 17 (dev Docker y prod)
- **Estilos:** Tailwind CSS v4 + DaisyUI v5
- **Archivos estáticos:** Whitenoise
- **Automatización:** n8n (opcional, subdominio propio en producción)
- **Seguridad:** django-axes, django-csp, headers HTTP
- **Producción:** Docker Compose + Nginx (gzip)

## Estructura

```
├── core/               # Configuración del proyecto
│   ├── settings.py     # Settings único (dev y prod por variables de entorno)
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── home/               # App principal
│   ├── sitemaps.py     # Sitemap de vistas estáticas
│   └── migrations/
├── theme/              # App Tailwind
│   └── static_src/
│       ├── package.json
│       └── src/styles.css
├── templates/
│   ├── base.html       # Base con OG tags, favicon, meta description
│   ├── 404.html
│   ├── 500.html
│   └── robots.txt
├── static/
│   └── img/
│       ├── favicon.svg         # Reemplazar con tu favicon
│       └── og-default.jpg      # Reemplazar con tu imagen OG (1200x630)
├── n8n/
│   └── workflows/              # Workflows exportados (versionados en git)
├── docker/
│   ├── init-db.sql             # Crea la base de datos de n8n en postgres
│   ├── n8n.Dockerfile          # Imagen custom n8n con Python 3.12
│   └── n8n-export.sh           # Script de exportación de workflows
├── volumes/            # Bind mounts de producción (generado, no versionado)
├── db/                 # Datos PostgreSQL de producción (generado, no versionado)
├── staticfiles/        # Salida de collectstatic (generado)
├── media/              # Uploads de usuarios (generado)
├── requirements.txt        # Dependencias de producción
├── requirements-dev.txt    # Dependencias de desarrollo
├── Dockerfile          # Multi-stage: Node (CSS) + Python
├── docker-compose.yml      # Producción: Django + PostgreSQL (+ n8n con profile)
├── docker-compose.dev.yml  # Desarrollo: PostgreSQL + n8n
├── entrypoint.sh       # Migraciones + Gunicorn
├── nginx.conf          # Plantilla nginx — bloque Django
├── nginx-n8n.conf      # Plantilla nginx — bloque n8n (usado si N8N_DOMAIN está definido)
├── nginx-deploy.sh     # Instala/actualiza config de nginx
├── deploy.sh           # Script de despliegue en VPS
└── Makefile
```

## Desarrollo local

### 1. Clonar y configurar entorno

```bash
git clone <repo>
cd <proyecto>
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
make install
```

### 2. Variables de entorno

```bash
cp .env.example .env
```

Para desarrollo con Django local + SQLite, basta con:

```env
DEBUG=True
```

Para desarrollo con PostgreSQL y n8n en Docker:

```env
DEBUG=True
PROJECT_NAME=miproyecto
POSTGRES_DB=miproyecto_db
POSTGRES_USER=miproyecto_user
POSTGRES_PASSWORD=contraseña
N8N_ENCRYPTION_KEY=dev-key-cualquiera
```

### 3. Iniciar el servidor

**Solo Django (SQLite):**
```bash
make dev
```

**Con PostgreSQL + n8n en Docker:**
```bash
make dev-up   # levanta PostgreSQL y n8n en Docker
make dev      # corre Django localmente apuntando al postgres del contenedor
```

O manualmente en dos terminales:
```bash
# Terminal 1 — watcher de Tailwind
python manage.py tailwind start

# Terminal 2 — servidor Django
python manage.py migrate
python manage.py runserver
```

- Django: http://127.0.0.1:8000
- n8n: http://localhost:5678

## n8n — flujo dev → producción

Los workflows se versionan en git dentro de `n8n/workflows/`.

```bash
# 1. Exportar workflows desde el contenedor de desarrollo
make n8n-export

# 2. Commitear y subir
git add n8n/workflows/
git commit -m "feat: actualizar workflows n8n"
git push

# 3. Desplegar (importa automáticamente en producción)
make deploy
```

En producción, n8n corre en su propio subdominio: `https://proyecto-n8n.tudominio.com`.

## Producción (VPS)

### 1. Configurar el `.env`

```bash
cp .env.example .env
nano .env
```

Variables obligatorias en producción:

```env
PROJECT_NAME=miproyecto
DOMAIN=tudominio.com
APP_PORT=8000
ADMIN_URL=mi-panel-secreto/

DEBUG=False
SECRET_KEY=una-clave-secreta-segura

POSTGRES_DB=miproyecto_db
POSTGRES_USER=miproyecto_user
POSTGRES_PASSWORD=contraseña-segura
```

Para habilitar n8n, añadir también:

```env
N8N_ENCRYPTION_KEY=clave-larga-y-secreta
N8N_DOMAIN=proyecto-n8n.tudominio.com
N8N_BASE_URL=https://proyecto-n8n.tudominio.com
```

> Si `N8N_DOMAIN` no está definido, el contenedor n8n no se levanta y el bloque nginx de n8n no se genera. No es necesario eliminar nada del proyecto — simplemente omitir esas variables.

> `N8N_ENCRYPTION_KEY` debe mantenerse constante — cambiarla invalida todas las credenciales guardadas en n8n.

### 2. Configurar nginx (primera vez)

```bash
make nginx
```

El script `nginx-deploy.sh`:
1. Genera `{PROJECT_NAME}.conf` a partir de `nginx.conf`
2. Si `N8N_DOMAIN` está definido, agrega el bloque de n8n desde `nginx-n8n.conf`
3. Copia la config a `/etc/nginx/sites-available/` y crea el symlink
4. Valida y recarga nginx

> Solo ejecutar cuando cambie `nginx.conf`/`nginx-n8n.conf` o en el primer deploy. No se ejecuta en cada `make deploy` para no sobreescribir la config de Certbot.

### 3. SSL con Certbot (primera vez)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d tudominio.com -d www.tudominio.com

# Si n8n está habilitado:
sudo certbot --nginx -d proyecto-n8n.tudominio.com
```

### 4. Desplegar

```bash
make deploy
```

El script `deploy.sh`:
1. `git pull` para actualizar el código
2. Si `N8N_DOMAIN` está definido: ajusta permisos del volumen n8n y activa el profile
3. Reconstruye y reinicia los contenedores Docker (el Dockerfile compila el CSS con Node)

## Settings

El archivo `core/settings.py` se adapta automáticamente según las variables de entorno:

| Variable presente | Comportamiento |
|---|---|
| `DEBUG=True` | SQLite, email en consola, Tailwind y browser-reload activos |
| `POSTGRES_DB` definido | Usa PostgreSQL |
| `EMAIL_HOST` definido | Usa backend SMTP |
| `DEBUG=False` | HSTS, CSRF seguro, sin herramientas de dev |

## Personalizar antes de usar

- `static/img/favicon.svg` — reemplazar con el favicon del proyecto
- `static/img/og-default.jpg` — imagen por defecto para redes sociales (1200×630px)
- `ADMINS` en `settings.py` — cambiar el email del administrador
- `LANGUAGE_CODE` y `TIME_ZONE` en `settings.py` — ajustar a tu región

## Comandos

```bash
make install      # pip install + tailwind install
make dev-up       # levanta PostgreSQL + n8n en Docker
make dev          # migrate + tailwind start + runserver
make dev-down     # detiene los contenedores de desarrollo
make n8n-export   # exporta workflows de n8n a n8n/workflows/
make migrate      # python manage.py migrate
make migrations   # python manage.py makemigrations
make superuser    # python manage.py createsuperuser
make collect      # collectstatic
make nginx        # instala/actualiza config de nginx (primera vez)
make deploy       # bash deploy.sh
make logs         # docker compose logs -f django
make down         # docker compose down
```

```bash
# Nueva app
python manage.py startapp nombre_app

# Acceder al contenedor Django
docker compose exec django bash

# Backup de la base de datos
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql
```
