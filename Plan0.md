# Plan: Time Tracker App — RedLine GS

## Descripción del sistema

Una aplicación de control de tiempo de trabajo para empleados compuesta por tres partes:

### Web app (accesible desde cualquier navegador)
- Login con Nextcloud (sky.redlinegs.com) via Nextcloud Login Flow v2
- Botón "Iniciar jornada" que registra hora de inicio
- Botón "Finalizar jornada" que abre modal con dos campos:
  1. Actividades realizadas hoy
  2. Actividades planificadas para mañana
- Al enviar el modal finaliza la jornada y detiene las capturas

### Agente Windows (.exe)
- Corre en segundo plano silenciosamente, sin interfaz gráfica
- Arranca automáticamente con Windows (startup)
- Cada 30 minutos consulta la API: ¿hay jornada activa para este usuario?
- Si hay jornada activa → captura pantalla y la envía al servidor
- Si no hay jornada activa → duerme hasta el próximo ciclo

### Backend Django
- Gestiona toda la base de datos con PostgreSQL
- API REST para la web app y el agente
- Autenticación via Nextcloud Login Flow v2
- Django Admin configurado como CRM completo

---

## Autenticación con Nextcloud Login Flow v2

Servidor Nextcloud: sky.redlinegs.com (ya en producción, no modificar)

Flujo:
1. Empleado abre la web app y hace clic en "Entrar con Nextcloud"
2. Django llama a: POST https://sky.redlinegs.com/index.php/login/v2
3. Nextcloud devuelve un loginUrl → redirigir al empleado ahí
4. Empleado confirma en Nextcloud
5. Django hace polling a Nextcloud hasta obtener appPassword + loginName
6. Django obtiene username y email del empleado via:
   GET https://sky.redlinegs.com/ocs/v1.php/cloud/users/{loginName}
   Header: OCS-APIREQUEST: true
7. Django busca o crea el Employee con ese username/email
8. Django emite JWT token para la sesión
9. Ese mismo JWT token se usa en el agente .exe

---

## Stack tecnológico

### Web frontend
- Django Templates + TailwindCSS +Diasyui
- JavaScript vanilla para el modal y llamadas a la API

### Backend
- Django 5.x
- Django REST Framework
- SimpleJWT para tokens
- requests (para comunicarse con Nextcloud API)
- PostgreSQL (gestionado por Django, instalado en el host del VPS)
- Nginx + Gunicorn
- Docker Compose

### Agente Windows
- Python 3.x
- Pillow (capturas de pantalla)
- requests (HTTP al servidor)
- schedule (timer cada 30 min)
- pywin32 (arrancar con Windows)
- PyInstaller para generar el .exe

---

## Modelos de base de datos

### Employee
Extiende User de Django via OneToOneField
Campos: nextcloud_username, email, full_name, department, is_active, created_at

### Workday
Campos: employee (FK), start_time, end_time, duration_minutes
Status: in_progress / completed / incomplete

### DailyReport
Uno por jornada (OneToOne con Workday)
Campos: workday (OneToOne FK), activities_done, activities_planned, submitted_at

### Screenshot
Campos: employee (FK), workday (FK), file_path, captured_at


## API Endpoints

### Autenticación
POST   /api/auth/nextcloud/start/     → inicia Login Flow con Nextcloud
POST   /api/auth/nextcloud/poll/      → polling hasta obtener token
GET    /api/auth/me/                  → datos del usuario autenticado

### Jornada (requiere JWT)
POST   /api/workday/start/            → inicia jornada, devuelve workday_id
POST   /api/workday/end/              → finaliza jornada + guarda reporte
GET    /api/workday/active/           → consulta si hay jornada activa (usa el agente)

### Screenshots (requiere JWT)
POST   /api/screenshot/               → recibe imagen + workday_id, guarda en disco

---

## Estructura de carpetas del proyecto

timetracker/
├── backend/
│   ├── config/           # settings, urls, wsgi
│   ├── employees/        # modelo Employee + admin
│   ├── workdays/         # modelos Workday + DailyReport + admin
│   ├── screenshots/      # modelo Screenshot + admin + almacenamiento
│   ├── authentication/   # Nextcloud Login Flow + JWT
│   └── api/              # serializers + views + urls
├── frontend/
│   └── templates/        # Django templates (login, dashboard, modal)
├── agent/
│   └── agent.py          # script del agente Windows
├── docker-compose.yml
├── nginx.conf
└── .env

---

## Django Admin (CRM)

Configurar el admin para:
- Ver jornadas por empleado con filtros por fecha y departamento
- Ver DailyReport inline dentro de cada jornada
- Ver galería de screenshots inline dentro de cada jornada
- Exportar jornadas a CSV
- Dashboard con resumen del día: cuántos empleados activos, jornadas completadas

---

## Configuración del agente Windows

El agente .exe se configura con un archivo config.json en la misma carpeta:

```json
{
  "server_url": "https://timetracker.redlinegs.com",
  "jwt_token": "TOKEN_DEL_EMPLEADO",
  "capture_interval_minutes": 30
}
```

El token JWT se genera la primera vez que el empleado hace login en la web app.
El empleado (o el admin) copia ese token al config.json del agente.

---

## Docker Compose para VPS

Servicios necesarios:
- django (gunicorn)
- nginx
- redis (para caché de sesiones)
- PostgreSQL

---

## Almacenamiento de screenshots

Las capturas se guardan en disco en el VPS, pero en el admin debe existir la opcion de modificar la ruta de guardado, se debe dividir por capeta de usuarios

/media/screenshots/{nextcloud_username}/{YYYY-MM-DD}/screenshot_{HH-MM}.jpg

Compatible con la estructura de Nextcloud existente.

---

## Orden de construcción

1. Proyecto Django: Usar el skeleton
2. Modelos: Employee, Workday, DailyReport, Screenshot con migraciones
3. Django Admin configurado como CRM (filtros, inlines, exportación CSV)
4. Autenticación: Nextcloud Login Flow v2 + emisión de JWT
5. API REST: todos los endpoints con Django REST Framework + SimpleJWT
6. Frontend: Django templates (login con Nextcloud, dashboard, modal de cierre)
7. Agente Windows: script Python + empaquetado con PyInstaller (.exe)
8. Deploy: nginx.conf + docker-compose.yml listo para el VPS

---

## Consideraciones importantes

- El servidor Nextcloud sky.redlinegs.com ya está en producción, no se modifica
- Todos los empleados ya tienen cuenta en ese Nextcloud
- Nginx ya está instalado en el VPS
- El agente .exe es silencioso, sin interfaz, corre en background
- El sistema debe ser escalable para agregar en el futuro: proyectos, clientes, nómina, reportes PDF

---
