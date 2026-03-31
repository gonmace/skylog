# Skylog

Sistema de registro de jornadas y monitoreo de actividad para empleados. Un agente Windows captura pantallas en segundo plano y las almacena en el servidor o en Nextcloud. Los ejecutivos pueden ver el estado de su equipo en tiempo real desde el dashboard.

## Stack

- **Backend:** Django 5.1, Django Channels 4 (ASGI), Daphne
- **Autenticación:** Nextcloud OAuth2 + JWT (SimpleJWT con blacklist)
- **WebSockets:** Django Channels + Redis (estado del agente en tiempo real, capturas inmediatas)
- **Base de datos:** SQLite (dev local) / PostgreSQL 17 (Docker y prod)
- **Estilos:** Tailwind CSS v4 + DaisyUI v5
- **Archivos estáticos:** Whitenoise
- **Almacenamiento de capturas:** Local (`media/`) o Nextcloud (WebDAV)
- **Seguridad:** django-axes (brute-force), django-csp, HSTS, DRF throttling, JWT blacklist
- **Producción:** Docker Compose + Nginx (HTTPS + Let's Encrypt)

---

## Estructura

```
├── core/               # Configuración del proyecto
│   ├── settings.py     # Settings único (dev/prod por variables de entorno)
│   ├── urls.py         # URLs raíz + health check (/health/)
│   └── asgi.py         # ProtocolTypeRouter HTTP + WebSocket
├── agent_ws/           # App Django Channels
│   ├── consumers.py    # AgentConsumer: marca agent_online=True/False en connect/disconnect
│   ├── auth.py         # Validación JWT en handshake WS
│   └── routing.py      # ws/agent/<employee_id>/
├── authentication/     # OAuth2, activación del agente, API auth
│   ├── views.py        # OAuth2 flow, AgentTokenPollView, AgentDownloadView
│   ├── api_urls.py     # /api/auth/...
│   └── models.py       # AgentRegistration, AgentActivationToken
├── employees/          # Modelo Employee (vinculado a User de Django)
│   └── models.py       # Employee: agent_online, agent_last_seen, agent_version, capturas, etc.
├── screenshots/        # Modelo Screenshot + upload a Nextcloud/local
├── workdays/           # Jornadas laborales
│   ├── models.py       # Workday, InactivityPeriod, DailyReport, CaptureConfig
│   ├── views.py        # API REST de jornadas + EmployeeOverviewView
│   └── api_urls.py     # /api/workday/...
├── home/               # Landing page pública
├── agent/              # Agente Windows (Python → .exe)
│   ├── agent.py        # Captura, JWT, WebSocket, auto-activación
│   ├── version.py      # Fuente única de la versión del agente
│   ├── requirements-agent.txt
│   ├── redline_agent.spec  # Config PyInstaller
│   └── build.bat       # Script de compilación
├── templates/
│   ├── base.html
│   ├── dashboard/
│   │   └── dashboard.html  # Template único: employee + executive + no-access
│   └── authentication/
├── static/
│   └── dashboard/js/dashboard.js  # SPA logic: vista employee/executive por JS
├── docker/
│   └── init-db.sql     # Inicialización de PostgreSQL
├── Dockerfile          # Multi-stage: Node (CSS) + Python
├── docker-compose.yml      # Prod: Django + PostgreSQL + Redis
├── docker-compose.dev.yml  # Dev: PostgreSQL + Redis
├── entrypoint.sh       # Migraciones + collectstatic + Daphne
├── nginx.conf          # Plantilla nginx (HTTPS + WebSocket + security headers)
├── nginx-deploy.sh     # Instala/actualiza config de nginx en el VPS
├── deploy.sh           # Script de despliegue en VPS (valida DEBUG=False)
└── Makefile
```

---

## Roles y autenticación

El sistema usa **Nextcloud OAuth2** para autenticar usuarios. No hay registro propio: los empleados se crean automáticamente al hacer login la primera vez.

| Rol | Condición | Acceso |
|---|---|---|
| **Ejecutivo** | Pertenece al grupo `skylog` en Nextcloud | Dashboard ejecutivo: ve a todos los empleados en tiempo real |
| **Empleado** | Cualquier otro usuario de Nextcloud | Dashboard propio: jornadas, capturas, estado del agente |
| **Sin acceso** | `skylog_access=False` en el admin | Ve una pantalla bloqueada; el ejecutivo puede habilitarlo |

El agente Windows se activa por separado (ver sección Agente).

---

## Dashboard

El dashboard es una **single-page** en `/dashboard/`. El mismo template sirve las tres vistas; el JS llama a `/api/auth/me/` al cargar y muestra la sección correcta según el perfil.

### Vista empleado

- **Estado del agente:** Online/Offline en tiempo real (WebSocket connect/disconnect). Si está offline, los botones de jornada se deshabilitan.
- **Onboarding:** Si el empleado nunca instaló el agente (`agent_version` vacío), aparece una tarjeta de setup con pasos y botón de descarga. Desaparece automáticamente al detectar el agente.
- **Jornada:** Iniciar / Finalizar. Al finalizar se pide un reporte diario (actividades realizadas + planificadas para mañana).
- **Versión del agente:** Se muestra con badge de advertencia si hay una versión más nueva disponible.

### Vista ejecutivo

- **Tabla de empleados** con estado en tiempo real (online/offline, jornada activa, minutos inactivos).
- **Captura inmediata** por empleado (envía comando al agente vía WebSocket).
- **Toggles** por empleado:
  - `screenshots_enabled`: activa/desactiva capturas de pantalla
  - `skylog_access`: habilita/deshabilita acceso al dashboard
- Los cambios en los toggles se reflejan inmediatamente en la tabla.

---

## Jornadas y modelos de datos

```
Workday          — una jornada laboral (in_progress / completed / incomplete)
  └── InactivityPeriod  — períodos donde el agente estuvo desconectado
  └── DailyReport       — reporte al finalizar (actividades hechas + planificadas)

CaptureConfig    — singleton con el intervalo global de captura (por defecto 30 min)
Employee.capture_interval_minutes — override por empleado (null = usar global)
```

El estado online del agente (`agent_online`) se actualiza en tiempo real: `True` al conectar WebSocket, `False` al desconectar.

---

## Desarrollo local

### Requisitos previos

- Python 3.11+
- Node.js 18+ (para compilar Tailwind)
- Docker Desktop (opcional, para PostgreSQL + Redis)

### 1. Clonar y configurar entorno Python

```bash
git clone <repo>
cd skylog
python -m venv .venv

# Linux/Mac
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements-dev.txt
python manage.py tailwind install
```

### 2. Variables de entorno

```bash
cp .env.example .env
```

Mínimo absoluto para arrancar (SQLite, sin Docker):

```env
DEBUG=True
SECRET_KEY=cualquier-clave-para-dev
```

Con PostgreSQL + Redis (más cercano a producción):

```env
DEBUG=True
PROJECT_NAME=skylog
POSTGRES_DB=skylog_db
POSTGRES_USER=skylog_user
POSTGRES_PASSWORD=contraseña
REDIS_URL=redis://localhost:6379/0
```

```bash
make dev-up   # levanta PostgreSQL + Redis en Docker
```

### 3. Migrar y crear superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Arrancar el servidor

En **Windows**, Tailwind y Django deben correr en terminales separadas:

```bash
# Terminal 1
python manage.py tailwind start

# Terminal 2
python manage.py runserver
```

En **Linux/Mac**:

```bash
make dev   # migrate + tailwind (background) + runserver
```

Accede a `http://127.0.0.1:8000`. El panel de admin está en la URL configurada en `ADMIN_URL` (por defecto `admin/`).

### 5. Configurar Nextcloud OAuth2 (dev)

1. En Nextcloud → Configuración → Seguridad → Clientes OAuth2 → Añadir cliente
2. URI de redirección: `http://localhost:8000/login/callback/`
3. Añadir en `.env`:
   ```env
   NEXTCLOUD_SERVER_URL=https://tu-nextcloud.com
   NEXTCLOUD_OAUTH2_CLIENT_ID=...
   NEXTCLOUD_OAUTH2_CLIENT_SECRET=...
   NEXTCLOUD_OAUTH2_REDIRECT_URI=http://localhost:8000/login/callback/
   ```

Sin Nextcloud, puedes crear usuarios desde el admin y forzar la sesión manualmente.

### 6. Correr el agente en desarrollo

```bash
cd agent
pip install -r requirements-agent.txt
python agent.py
```

El agente se conecta a `http://localhost:8000`. Los logs se escriben en `agent/redlinegs_agent.log`.

---

## Agente Windows

### Activación

Al ejecutar el agente por primera vez, abre el navegador en `/login/setup/?device=<token>`. Si el usuario ya está autenticado en el dashboard, un clic autoriza el agente directamente. Si no, pasa por el flujo OAuth2 completo.

El agente también está disponible para descarga directa desde el **dashboard** (botón en la tarjeta de onboarding).

### Compilar el .exe

Requiere Windows con Python 3.11+:

```bash
cd agent
pip install -r requirements-agent.txt
build.bat    # genera dist/redline_agent.exe
```

### Instalación en Windows

```bash
redline_agent.exe --install    # agrega al inicio de sesión (HKCU, sin admin)
redline_agent.exe --uninstall  # quita del inicio de sesión
```

### Comportamiento

- Captura pantalla según el intervalo configurado (global o override por empleado)
- Mantiene WebSocket persistente; el dashboard ejecutivo ve el estado online en tiempo real
- Responde a capturas inmediatas solicitadas desde el dashboard en < 1 segundo
- Renueva el JWT automáticamente con el refresh token (válido 7 días)
- Si el refresh token expira, abre el navegador para re-autenticación
- Reconexión WebSocket con backoff exponencial: 5s → 10s → … → 300s
- En caso de error de red, reintenta en 10 minutos

### Versión

Definida en `agent/version.py`. Se muestra en el dashboard con badge de advertencia si el agente del empleado está desactualizado.

---

## Almacenamiento de capturas

### Local (por defecto)

Las capturas se guardan en `media/screenshots/{nombre}/{YY-MM}/{DD-HHhMM}.jpg`.

### Nextcloud (opcional)

Si `NEXTCLOUD_SCREENSHOTS_USER` está definido, las capturas se suben vía WebDAV. Las URLs se sirven a través del proxy interno `/api/screenshot/<pk>/image/`.

```env
NEXTCLOUD_SCREENSHOTS_USER=skylog-agent
NEXTCLOUD_SCREENSHOTS_PASSWORD=app-password-de-nextcloud
NEXTCLOUD_SCREENSHOTS_FOLDER=Skylog/screenshots
```

---

## Producción (VPS)

### Requisitos previos

- Docker + Docker Compose
- Nginx (`apt install nginx`)
- Certbot (`apt install certbot python3-certbot-nginx`)
- Dominio apuntando al VPS

### 1. Clonar el repositorio

```bash
git clone <repo>
cd skylog
```

### 2. Configurar el `.env`

```bash
cp .env.example .env
nano .env
```

Variables obligatorias:

```env
PROJECT_NAME=skylog
DOMAIN=skylog.tudominio.com
APP_PORT=8000
DEBUG=False

SECRET_KEY=genera-con-python-secrets-token-urlsafe-50
ALLOWED_HOSTS=skylog.tudominio.com
CSRF_TRUSTED_ORIGINS=https://skylog.tudominio.com

ADMIN_URL=mi-panel-secreto/
ADMIN_NAME=Admin
ADMIN_EMAIL=admin@tudominio.com

POSTGRES_DB=skylog_db
POSTGRES_USER=skylog_user
POSTGRES_PASSWORD=contraseña-segura

REDIS_URL=redis://redis:6379/0

NEXTCLOUD_SERVER_URL=https://tu-nextcloud.com
NEXTCLOUD_OAUTH2_CLIENT_ID=...
NEXTCLOUD_OAUTH2_CLIENT_SECRET=...
NEXTCLOUD_OAUTH2_REDIRECT_URI=https://skylog.tudominio.com/login/callback/
```

Para generar `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### 3. Certificado SSL (solo la primera vez)

`nginx.conf` ya incluye el bloque HTTPS con Let's Encrypt. Obtén el certificado antes del primer despliegue:

```bash
sudo certbot certonly --standalone -d skylog.tudominio.com
```

### 4. Instalar config de nginx (solo la primera vez)

```bash
make nginx
```

Genera e instala la config de nginx a partir de `nginx.conf` con los valores del `.env`.

### 5. Desplegar

Primera vez y cada actualización:

```bash
make deploy
```

El script `deploy.sh`:
1. Valida que `DEBUG=False` esté en el `.env` (sale con error si no)
2. `git pull origin main`
3. Reconstruye los contenedores Docker (compila CSS, instala deps)
4. `entrypoint.sh` ejecuta migraciones y arranca Daphne

### 6. Crear superusuario (solo la primera vez)

```bash
docker compose exec django python manage.py createsuperuser
```

---

## Endpoints principales

| Método | URL | Descripción |
|---|---|---|
| `GET` | `/health/` | Health check — `{"status":"ok"}` |
| `GET` | `/api/auth/me/` | Perfil del usuario autenticado + versión del agente |
| `POST` | `/api/auth/token/refresh/` | Renovar JWT (refresh token) |
| `GET` | `/api/auth/agent/poll/` | El agente pollea para obtener sus tokens (throttled: 30/min) |
| `POST` | `/api/auth/agent/authorize/` | Autorizar agente desde el browser |
| `GET` | `/api/auth/agent/download/` | Descargar el ejecutable del agente |
| `GET` | `/api/workday/active/` | Estado de jornada activa + heartbeat del agente |
| `POST` | `/api/workday/start/` | Iniciar jornada |
| `POST` | `/api/workday/end/` | Finalizar jornada (con reporte diario) |
| `GET` | `/api/workday/overview/` | Vista ejecutivo: todos los empleados en tiempo real |
| `POST` | `/api/workday/capture/<id>/` | Ejecutivo: solicitar captura inmediata |
| `PATCH` | `/api/workday/employee/<id>/skylog/` | Ejecutivo: toggle acceso Skylog |
| `PATCH` | `/api/workday/employee/<id>/screenshots/` | Ejecutivo: toggle capturas |
| `WS` | `ws/agent/` | WebSocket del agente (JWT en query param) |

---

## Settings — comportamiento por variable de entorno

| Variable presente | Comportamiento |
|---|---|
| `DEBUG=True` | SQLite, email en consola, Tailwind y browser-reload activos |
| `POSTGRES_DB` definido | Usa PostgreSQL |
| `REDIS_URL` definido | Usa RedisChannelLayer; si no, InMemoryChannelLayer |
| `NEXTCLOUD_SCREENSHOTS_USER` definido | Capturas vía WebDAV a Nextcloud |
| `EMAIL_HOST` definido | Usa backend SMTP |
| `ADMIN_NAME` + `ADMIN_EMAIL` definidos | Recibe emails de errores 500 vía `ADMINS` |
| `DEBUG=False` | HSTS (1 año + preload + subdomains), CSRF seguro, SSL redirect |

---

## Seguridad

- **Brute-force:** django-axes bloquea IPs/usuarios tras 5 intentos fallidos (1h de cooldown)
- **JWT:** access token 2h, refresh token 7 días, blacklist activado en rotación
- **CSP:** `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, frame-ancestors restringido a Nextcloud
- **HSTS:** 1 año, incluye subdominios y preload
- **Throttling DRF:** anónimos 60/min, usuarios autenticados 300/min; AgentTokenPoll 30/min
- **Admin URL:** aleatorizado vía `ADMIN_URL` env var
- **Nginx headers:** `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`

---

## Referencia de comandos

```bash
make install      # pip install -r requirements-dev.txt + tailwind install
make dev-up       # levanta PostgreSQL + Redis en Docker (dev)
make dev-down     # detiene los contenedores de desarrollo
make dev-logs     # logs de los contenedores de desarrollo
make dev          # migrate + tailwind start + runserver (Linux/Mac)
make migrate      # python manage.py migrate
make migrations   # python manage.py makemigrations
make superuser    # python manage.py createsuperuser
make collect      # collectstatic
make shell        # python manage.py shell
make nginx        # instala/actualiza config de nginx en el VPS
make deploy       # bash deploy.sh
make logs         # docker compose logs -f django
make down         # docker compose down
```

```bash
# Acceder al contenedor Django en producción
docker compose exec django bash

# Backup de la base de datos
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql
```
