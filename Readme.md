# Skylog

Skylog mantiene a todo el equipo sincronizado: sabe quién está conectado, cómo está su jornada y qué tiene entre manos. Esa visibilidad compartida —y el historial que va acumulando— es la base sobre la que nuestro agente de IA trabajará con contexto real, no con suposiciones.

## Stack

- **Backend:** Django 5.1, Django Channels 4 (ASGI), Daphne
- **Autenticación:** Nextcloud OAuth2 + JWT (SimpleJWT con blacklist) + login username/password para usuarios móviles
- **WebSockets:** Django Channels + Redis (estado del agente en tiempo real, capturas inmediatas, notificaciones de mensajes)
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
│   ├── consumers.py    # AgentConsumer + DashboardConsumer (notificaciones browser)
│   ├── auth.py         # Validación JWT en handshake WS
│   └── routing.py      # ws/agent/ + ws/dashboard/
├── authentication/     # OAuth2, activación del agente, API auth
│   ├── views.py        # OAuth2 flow, AgentTokenPollView, MobileLoginView, DevLoginView
│   ├── api_urls.py     # /api/auth/...
│   └── models.py       # AgentRegistration, AgentActivationToken
├── employees/          # Modelo Employee (vinculado a User de Django)
│   └── models.py       # Employee: agent_online, is_mobile, capturas, etc.
├── screenshots/        # Modelo Screenshot + upload a Nextcloud/local
├── workdays/           # Jornadas laborales
│   ├── models.py       # Workday, InactivityPeriod, DailyReport, CalendarNote, EmployeeLeave
│   ├── views.py        # API REST de jornadas, calendarios, notas, ausencias
│   └── api_urls.py     # /api/workday/...
├── home/               # Landing page pública
├── agent/              # Agente Windows (Python → .exe)
│   ├── agent.py        # Captura, JWT, WebSocket, auto-activación
│   ├── version.py      # Fuente única de la versión del agente
│   ├── requirements-agent.txt
│   ├── redline_agent.spec  # Config PyInstaller
│   ├── installer.iss   # Script Inno Setup (genera RedLineGS_setup.exe)
│   └── build.bat       # Script de compilación
├── templates/
│   ├── base.html
│   ├── dashboard/
│   │   └── dashboard.html  # Template único: employee + executive + no-access
│   ├── mobile/
│   │   └── dashboard.html  # SPA móvil autónoma (login + jornada + GPS)
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

| Rol | Condición | Acceso |
|---|---|---|
| **Ejecutivo** | Pertenece al grupo `skylog` en Nextcloud | Dashboard ejecutivo: ve a todos los empleados en tiempo real |
| **Empleado** | Cualquier otro usuario de Nextcloud | Dashboard propio: jornadas, capturas, estado del agente |
| **Empleado móvil** | `is_mobile=True` en el admin | Dashboard móvil en `/mobile/`: sin agente, GPS requerido para cerrar jornada |
| **Sin acceso** | `skylog_access=False` en el admin | Ve una pantalla bloqueada; el ejecutivo puede habilitarlo |

- **Empleados normales:** se autentican con Nextcloud OAuth2. Se crean automáticamente al hacer login la primera vez.
- **Empleados móviles:** se crean manualmente en el admin Django. Se autentican con usuario/contraseña en `/mobile/`.

---

## Dashboard

El dashboard principal (`/dashboard/`) es una **single-page**: el mismo template sirve las tres vistas; el JS llama a `/api/auth/me/` al cargar y muestra la sección correcta.

### Vista empleado

- **Estado del agente:** Online/Offline en tiempo real (WebSocket). Si está offline, los botones se deshabilitan.
- **Jornada:** Iniciar / Finalizar. Al finalizar se pide reporte diario y se dispara una captura de pantalla automática.
- **Calendario mensual:** muestra las horas trabajadas por día con el total semanal. Días con jornada auto-cerrada se marcan en amarillo con tooltip de alerta. Días con ausencia (vacación/licencia/permiso) se muestran con color según tipo.
- **Notas del equipo:** las notas globales del ejecutivo (feriados, eventos) aparecen en el calendario del empleado al pasar el mouse.
- **Versión del agente:** badge de advertencia si hay versión más nueva disponible.
- **Onboarding:** si el empleado nunca instaló el agente, aparece tarjeta de setup.

### Vista ejecutivo

- **Tabla de empleados** con estado en tiempo real (online/offline, jornada activa, minutos inactivos, ubicación GPS si es móvil).
- **Captura inmediata** por empleado (envía comando al agente vía WebSocket).
- **Calendario por empleado:** modal con el historial mensual de cada empleado. Permite registrar ausencias (vacación / licencia / permiso) con rango de fechas.
- **Calendario del equipo:** calendario global al pie del dashboard para registrar notas (feriados, eventos). Click en cualquier día para añadir/editar/eliminar.
- **Jornadas auto-cerradas:** días donde el empleado no cerró su jornada se marcan en rojo con el texto "Jornada no finalizada".
- **Toggles** por empleado: `screenshots_enabled` y `skylog_access`.

### Dashboard móvil (`/mobile/`)

SPA autónoma para empleados sin agente Windows:

- Login con usuario/contraseña (sin Nextcloud)
- Iniciar/finalizar jornada con timer
- **GPS obligatorio** para finalizar: si el navegador deniega la ubicación, el botón queda bloqueado
- Tokens JWT gestionados en localStorage

---

## Jornadas y modelos de datos

```
Workday          — una jornada laboral (in_progress / completed / incomplete)
  ├── auto_closed       — True si fue cerrada automáticamente a las 17:00
  ├── start_latitude / start_longitude  — ubicación al iniciar (usuarios móviles)
  ├── end_latitude / end_longitude      — ubicación al finalizar (usuarios móviles)
  └── InactivityPeriod  — períodos donde el agente estuvo desconectado
  └── DailyReport       — reporte al finalizar (actividades hechas + planificadas)

CalendarNote     — nota del ejecutivo en una fecha del calendario del equipo
  └── note_type: holiday | event | other

EmployeeLeave    — ausencia de un empleado en un rango de fechas
  └── leave_type: vacacion | licencia | permiso

CaptureConfig    — singleton con el intervalo global de captura (por defecto 30 min)
Employee.capture_interval_minutes — override por empleado (null = usar global)
Employee.is_mobile — True para empleados sin agente (acceso por /mobile/)
```

**Cierre automático de jornadas:** cada vez que se carga la vista ejecutiva (`/api/workday/overview/`), el sistema detecta jornadas `in_progress` de días anteriores (zona horaria GMT-4) y las cierra automáticamente a las 17:00, marcándolas con `auto_closed=True`.

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
ADMIN_URL=panel/
```

```bash
make dev-up   # levanta PostgreSQL + Redis en Docker
```

### 3. Migrar y crear superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

> **Nota:** el panel de admin está en la URL configurada en `ADMIN_URL` (ej. `http://localhost:8000/panel/`). Si te bloquea por demasiados intentos fallidos (django-axes), ejecuta `python manage.py axes_reset`.

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

### 5. Login rápido en desarrollo

Con `DEBUG=True` hay atajos para no necesitar Nextcloud:

```
http://localhost:8000/dev-login/?role=executive   # crea dev_executive y abre sesión
http://localhost:8000/dev-login/?role=employee    # crea dev_employee y abre sesión
```

### 6. Configurar Nextcloud OAuth2 (dev)

1. En Nextcloud → Configuración → Seguridad → Clientes OAuth2 → Añadir cliente
2. URI de redirección: `http://localhost:8000/login/callback/`
3. Añadir en `.env`:
   ```env
   NEXTCLOUD_SERVER_URL=https://tu-nextcloud.com
   NEXTCLOUD_OAUTH2_CLIENT_ID=...
   NEXTCLOUD_OAUTH2_CLIENT_SECRET=...
   NEXTCLOUD_OAUTH2_REDIRECT_URI=http://localhost:8000/login/callback/
   ```

### 7. Correr el agente en desarrollo

```bash
cd agent
pip install -r requirements-agent.txt
python agent.py
```

El agente se conecta a `http://localhost:8000`. Los logs se escriben en `%AppData%\RedLineGS\redlinegs_agent.log`.

### 8. Generar datos de prueba

```bash
python manage.py seed_dev_workdays           # genera jornadas para dev_employee (último mes)
python manage.py seed_dev_workdays --days 60 # últimos 60 días
python manage.py seed_dev_workdays --clear   # borra las jornadas existentes antes de generar
```

---

## Agente Windows

### Activación

Al ejecutar el agente por primera vez, abre el navegador en `/login/setup/?device=<token>`. Si el usuario ya está autenticado en el dashboard, un clic autoriza el agente directamente.

El agente también está disponible para descarga directa desde el **dashboard** (botón en la tarjeta de onboarding).

### Compilar el .exe

Requiere Windows con Python 3.11+:

```bash
cd agent
pip install -r requirements-agent.txt
build.bat    # genera dist/redline_agent.exe
```

### Crear el instalador (.exe setup) con Inno Setup

El archivo `agent/installer.iss` define un instalador completo para Windows usando **Inno Setup**. El instalador:

- Muestra una pantalla de bienvenida con descripción del producto (`agent/info_before.txt`)
- Copia `redline_agent.exe` a `%ProgramFiles%\RedLineGS\`
- Copia `config.json` (si está junto al setup.exe) a `%AppData%\RedLineGS\config.json`
- Registra el autostart en `HKCU` vía sección `[Registry]` (se limpia automáticamente al desinstalar)
- Cierra silenciosamente cualquier versión anterior del agente antes de instalar
- Arranca el agente automáticamente al finalizar
- Abre el dashboard en el navegador al presionar **Finalizar**

**Archivos necesarios en `agent/` para compilar:**

| Archivo | Descripción |
|---|---|
| `dist/redline_agent.exe` | Agente compilado con PyInstaller |
| `redlinegs.ico` | Ícono del instalador |
| `logo.bmp` | Logo para la pantalla de bienvenida (generado con `make agent-logo`) |
| `info_before.txt` | Texto de la pantalla de bienvenida |

**Generar `RedLineGS_setup.exe`:**

```bash
# Todo en un comando (genera logo.bmp + compila exe + compila installer):
make agent-build

# O paso a paso:
make agent-logo                  # convierte logo PNG a BMP
cd agent && pyinstaller redline_agent.spec   # genera dist/redline_agent.exe
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" agent/installer.iss
```

Requiere [Inno Setup 6](https://jrsoftware.org/isdl.php) instalado en la ruta por defecto.

**Distribución al empleado:**

El empleado recibe un ZIP con dos archivos:
```
RedLineGS_setup.exe   ← el instalador generado por Inno Setup
config.json           ← generado por el dashboard al crear el token de activación
```

El instalador detecta automáticamente el `config.json` junto a sí mismo, lo copia a `%AppData%\RedLineGS\` y el agente se activa silenciosamente sin abrir el navegador.

### Comportamiento

- Captura pantalla según el intervalo configurado (global o override por empleado)
- Captura automática al finalizar la jornada
- Mantiene WebSocket persistente; el dashboard ejecutivo ve el estado online en tiempo real
- Responde a capturas inmediatas solicitadas desde el dashboard en < 1 segundo
- Renueva el JWT automáticamente con el refresh token (válido 30 días)
- Reconexión WebSocket con backoff exponencial: 5s → 10s → … → 300s
- En caso de error de red, reintenta en 10 minutos

### Versión

Definida en `agent/version.py`. Se muestra en el dashboard con badge de advertencia si el agente del empleado está desactualizado.

---

## Almacenamiento de capturas

### Local (por defecto)

Las capturas se guardan en `media/screenshots/{nombre}/{YYYY-mes}/{DD-HHhMMmSS}.jpg`.

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

### 3. Instalar nginx y obtener SSL (solo la primera vez)

**Paso A — instalar config HTTP temporal:**

```bash
make nginx
```

**Paso B — obtener el certificado con certbot:**

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d skylog.tudominio.com
```

**Paso C — activar config HTTPS:**

```bash
make nginx
```

### 4. Actualizar la configuración de nginx

```bash
bash nginx-deploy.sh --force
```

### 5. Desplegar

```bash
make deploy
```

El script `deploy.sh`:
1. Valida que `DEBUG=False` esté en el `.env`
2. `git pull origin main`
3. Reconstruye los contenedores Docker
4. `entrypoint.sh` ejecuta migraciones y arranca Daphne

### 6. Crear superusuario (solo la primera vez)

```bash
docker compose exec django python manage.py createsuperuser
```

---

## Endpoints principales

| Método | URL | Descripción |
|---|---|---|
| `GET` | `/health/` | Health check |
| `GET` | `/api/auth/me/` | Perfil del usuario autenticado |
| `POST` | `/api/auth/token/refresh/` | Renovar JWT |
| `POST` | `/api/auth/mobile-login/` | Login usuario/contraseña (empleados móviles) |
| `GET` | `/api/auth/agent/poll/` | El agente pollea para obtener tokens |
| `POST` | `/api/auth/agent/authorize/` | Autorizar agente desde el browser |
| `GET` | `/api/auth/agent/download/` | Descargar el ejecutable del agente |
| `GET` | `/api/workday/active/` | Estado de jornada activa |
| `POST` | `/api/workday/start/` | Iniciar jornada (acepta `latitude`/`longitude`) |
| `POST` | `/api/workday/end/` | Finalizar jornada + captura automática (lat/lng obligatorio para móviles) |
| `GET` | `/api/workday/monthly/` | Calendario mensual del empleado autenticado |
| `GET` | `/api/workday/overview/` | Vista ejecutivo: todos los empleados en tiempo real |
| `GET` | `/api/employees/<id>/monthly/` | Ejecutivo: calendario mensual de un empleado |
| `GET/POST` | `/api/calendar/notes/` | Notas del calendario global del equipo |
| `DELETE` | `/api/calendar/notes/<id>/` | Eliminar nota del calendario |
| `GET/POST` | `/api/employees/<id>/leaves/` | Ausencias de un empleado |
| `DELETE` | `/api/employees/<id>/leaves/<id>/` | Eliminar ausencia |
| `POST` | `/api/workday/capture/<id>/` | Ejecutivo: captura inmediata |
| `PATCH` | `/api/workday/employee/<id>/skylog/` | Ejecutivo: toggle acceso Skylog |
| `PATCH` | `/api/workday/employee/<id>/screenshots/` | Ejecutivo: toggle capturas |
| `WS` | `ws/agent/` | WebSocket del agente (JWT en query param) |
| `WS` | `ws/dashboard/` | WebSocket del browser (notificaciones en tiempo real) |

---

## Settings — comportamiento por variable de entorno

| Variable presente | Comportamiento |
|---|---|
| `DEBUG=True` | SQLite, email en consola, Tailwind y browser-reload activos, SameSite=Lax en cookies |
| `POSTGRES_DB` definido | Usa PostgreSQL |
| `REDIS_URL` definido | Usa RedisChannelLayer; si no, InMemoryChannelLayer |
| `NEXTCLOUD_SCREENSHOTS_USER` definido | Capturas vía WebDAV a Nextcloud |
| `EMAIL_HOST` definido | Usa backend SMTP |
| `ADMIN_NAME` + `ADMIN_EMAIL` definidos | Recibe emails de errores 500 vía `ADMINS` |
| `DEBUG=False` | HSTS, CSRF seguro, SSL redirect, SameSite=None (para iframes cross-origin) |

---

## Seguridad

- **Brute-force:** django-axes bloquea IPs/usuarios tras 5 intentos fallidos (1h de cooldown). En dev: `python manage.py axes_reset`
- **JWT:** access token 2h, refresh token 30 días, blacklist activado en rotación
- **CSP:** `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, frame-ancestors restringido a Nextcloud
- **HSTS:** 1 año, incluye subdominios y preload (solo producción)
- **Throttling DRF:** anónimos 60/min, autenticados 300/min; AgentTokenPoll 30/min
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
make agent-install  # pip install -r agent/requirements-agent.txt
make agent-logo     # convierte logo PNG → BMP para el installer
make agent-build    # genera logo.bmp + redline_agent.exe + RedLineGS_setup.exe
```

```bash
# Acceder al contenedor Django en producción
docker compose exec django bash

# Backup de la base de datos
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql

# Resetear lockout de django-axes
python manage.py axes_reset
```
