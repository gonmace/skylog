"""
RedLine GS — Agente de capturas de pantalla para Windows
Corre silenciosamente en segundo plano, sin interfaz gráfica.

Uso:
  redline_agent.exe           -- ejecutar normalmente (activa si no tiene token)
  redline_agent.exe --install -- agregar al inicio de Windows (HKCU, sin admin)
  redline_agent.exe --uninstall -- quitar del inicio de Windows
"""

import json
import os
import sys
import time
import logging
import threading
import webbrowser
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

import requests
import websocket
from PIL import ImageGrab

# ── Config ────────────────────────────────────────────────────────────────────

APP_NAME = 'RedLineGSAgent'
from version import VERSION as AGENT_VERSION

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Config y logs en AppData — nunca junto al exe
_appdata = os.environ.get('APPDATA', BASE_DIR)
APP_DIR = os.path.join(_appdata, 'RedLineGS')
os.makedirs(APP_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(APP_DIR, 'config.json')
LOG_PATH = os.path.join(APP_DIR, 'redlinegs_agent.log')

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8',
)
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'server_url': 'https://skylog.redlinegs.com' if getattr(sys, 'frozen', False) else 'http://localhost:8000',
    'jwt_token': '',
    'capture_interval_minutes': 30,
}


PRODUCTION_SERVER_URL = 'https://skylog.redlinegs.com'


def load_config():
    # Si no existe un config en AppData, buscar config.json junto al exe (viene en el ZIP de descarga)
    if not os.path.exists(CONFIG_PATH):
        bundled = os.path.join(BASE_DIR, 'config.json')
        if os.path.exists(bundled):
            try:
                with open(bundled, encoding='utf-8') as f:
                    config = json.load(f)
                save_config(config)
                return config
            except Exception:
                pass
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_PATH, encoding='utf-8') as f:
        config = json.load(f)

    # Si no hay jwt ni activation_token, intentar recuperar activation_token del bundled config
    if not config.get('jwt_token', '').strip() and not config.get('activation_token', '').strip():
        bundled = os.path.join(BASE_DIR, 'config.json')
        if os.path.exists(bundled):
            try:
                with open(bundled, encoding='utf-8') as f:
                    bundled_config = json.load(f)
                token = bundled_config.get('activation_token', '').strip()
                if token:
                    config['activation_token'] = token
                    save_config(config)
            except Exception:
                pass

    # El exe compilado siempre usa el servidor de producción, ignorando lo que
    # haya en el config (evita configs de dev con localhost que se cuelan).
    if getattr(sys, 'frozen', False):
        if config.get('server_url') != PRODUCTION_SERVER_URL:
            config['server_url'] = PRODUCTION_SERVER_URL
            save_config(config)
    return config


def save_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ── Activación automática ─────────────────────────────────────────────────────

def needs_setup(config):
    jwt = config.get('jwt_token', '').strip()
    activation = config.get('activation_token', '').strip()
    return not jwt and not activation


def activate_with_token(config):
    """Intercambia el activation_token por JWT. Sin interacción del usuario."""
    server_url = config.get('server_url', '').rstrip('/')
    activation_token = config.get('activation_token', '').strip()

    log.info('Activando agente con token de un solo uso...')
    try:
        resp = requests.post(
            f"{server_url}/api/agent/activate/",
            json={'activation_token': activation_token},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            config['jwt_token'] = data['access']
            config['refresh_token'] = data['refresh']
            config['activation_token'] = ''
            config['employee_name'] = data.get('employee_name', '')
            config['employee_email'] = data.get('employee_email', '')
            save_config(config)
            log.info(f"Agente activado para: {data.get('employee_name')} ({data.get('employee_email')})")
            return config
        elif resp.status_code == 410:
            log.error('El token de activación ya fue usado o expiró. Descarga uno nuevo desde el dashboard.')
        elif resp.status_code == 404:
            log.error('Token de activación inválido.')
        else:
            log.error(f'Error en activación: {resp.status_code} {resp.text}')
    except Exception as e:
        log.error(f'Error conectando al servidor para activación: {e}')
    return None


NEEDS_REAUTH = object()  # centinela: refresh falló, hay que re-autenticar


def refresh_jwt(config):
    """Usa el refresh_token para obtener un nuevo access_token sin intervención del usuario.
    Devuelve el config actualizado, NEEDS_REAUTH si hay que re-autenticar, o None si es un
    error de red transitorio."""
    server_url = config.get('server_url', '').rstrip('/')
    refresh_token = config.get('refresh_token', '').strip()

    if not refresh_token:
        log.warning('Sin refresh_token. Iniciando re-autenticación...')
        return NEEDS_REAUTH

    try:
        resp = requests.post(
            f"{server_url}/api/auth/token/refresh/",
            json={'refresh': refresh_token},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            config['jwt_token'] = data['access']
            if 'refresh' in data:
                config['refresh_token'] = data['refresh']
            save_config(config)
            log.info('JWT renovado automáticamente.')
            return config
        else:
            log.warning('Refresh token inválido o expirado. Iniciando re-autenticación...')
            return NEEDS_REAUTH
    except Exception as e:
        log.error(f'Error de red renovando JWT: {e}')
        return None  # error transitorio, reintentar en el próximo ciclo


def run_setup(config):
    """Fallback: abre el navegador si no hay activation_token (instalación manual)."""
    server_url = config.get('server_url', '').rstrip('/')
    device_token = str(uuid.uuid4())

    setup_url = f"{server_url}/login/agent/setup/?device={device_token}"
    log.info(f'Activación necesaria. Abriendo navegador: {setup_url}')
    webbrowser.open(setup_url)

    log.info('Esperando que el empleado complete el login...')
    poll_url = f"{server_url}/api/agent/token/?device={device_token}"
    attempts = 0
    max_attempts = 120  # 10 min a 5s cada uno

    while attempts < max_attempts:
        time.sleep(5)
        attempts += 1
        try:
            resp = requests.get(poll_url, timeout=10)
            if resp.status_code in (202, 404):
                continue
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'ok':
                    config['jwt_token'] = data['access']
                    if data.get('refresh'):
                        config['refresh_token'] = data['refresh']
                    save_config(config)
                    try:
                        me = requests.get(
                            f"{server_url}/api/auth/me/",
                            headers={'Authorization': f"Bearer {config['jwt_token']}"},
                            timeout=10,
                        ).json()
                        config['employee_name'] = me.get('full_name', '')
                        config['employee_email'] = me.get('email', '')
                        save_config(config)
                        log.info(f"Agente activado para: {me.get('full_name')} ({me.get('email')})")
                    except Exception:
                        log.info('Token recibido y guardado. Agente activado.')
                    return config
        except Exception as e:
            log.error(f'Error en polling de activación: {e}')

    log.error('Tiempo de espera de activación agotado (10 min).')
    return None


# ── Windows startup ───────────────────────────────────────────────────────────

def install_startup():
    import winreg
    exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Windows\CurrentVersion\Run',
        0, winreg.KEY_SET_VALUE,
    )
    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
    winreg.CloseKey(key)
    print(f'[OK] Agregado al inicio de Windows como "{APP_NAME}"')


def uninstall_startup():
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Windows\CurrentVersion\Run',
        0, winreg.KEY_SET_VALUE,
    )
    try:
        winreg.DeleteValue(key, APP_NAME)
        print(f'[OK] Eliminado del inicio de Windows: "{APP_NAME}"')
    except FileNotFoundError:
        print(f'[INFO] No estaba registrado en el inicio de Windows.')
    winreg.CloseKey(key)


# ── Ping server (local health check para el dashboard) ───────────────────────

PING_PORT = 7337

_capture_event = threading.Event()
_force_capture = False  # True cuando el trigger viene del servidor (bypass de intervalo)


class _LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/ping':
            self._json(200, b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/trigger':
            _capture_event.set()  # despierta el loop principal
            self._json(200, b'{"status":"triggered"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self._cors_headers()
        self.end_headers()

    def _json(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        # Requerido por Chrome 94+ para permitir fetch desde HTTPS a localhost
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def log_message(self, *args):
        pass  # silencioso

    def handle_error(self, request, client_address):
        # Ignorar errores de conexión abortada por el cliente (WinError 10053, BrokenPipe)
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def start_ping_server():
    try:
        server = HTTPServer(('127.0.0.1', PING_PORT), _LocalHandler)
        server.serve_forever()
    except Exception as e:
        log.warning(f'No se pudo iniciar servidor local en puerto {PING_PORT}: {e}')


# ── WebSocket thread ──────────────────────────────────────────────────────────

WS_RECONNECT_DELAY_MIN = 5
WS_RECONNECT_DELAY_MAX = 300


def ws_thread():
    """Mantiene una conexión WebSocket persistente con el servidor.
    Cuando el servidor envía {"command":"capture"}, activa _capture_event."""
    delay = WS_RECONNECT_DELAY_MIN
    while True:
        config = load_config()
        server_url = config.get('server_url', '').rstrip('/')
        token = config.get('jwt_token', '').strip()

        if not token or not server_url:
            time.sleep(delay)
            continue

        ws_url = server_url.replace('https://', 'wss://').replace('http://', 'ws://')
        ws_url = f'{ws_url}/ws/agent/?token={token}&version={AGENT_VERSION}'

        connected = threading.Event()

        def on_open(ws):
            nonlocal delay
            delay = WS_RECONNECT_DELAY_MIN
            connected.set()
            log.info('WebSocket conectado al servidor.')

        def on_message(ws, message):
            global _force_capture
            try:
                data = json.loads(message)
                if data.get('command') == 'capture':
                    log.info('WebSocket: captura inmediata solicitada por el servidor.')
                    _force_capture = True
                    _capture_event.set()
            except Exception as e:
                log.warning(f'WebSocket: mensaje inválido: {e}')

        def on_error(ws, error):
            log.warning(f'WebSocket error: {error}')

        def on_close(ws, close_status_code, close_msg):
            if connected.is_set():
                log.info(f'WebSocket desconectado (código={close_status_code}).')

        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            log.warning(f'WebSocket excepción: {e}')

        log.info(f'WebSocket reconectando en {delay}s...')
        time.sleep(delay)
        delay = min(delay * 2, WS_RECONNECT_DELAY_MAX)


# ── Helpers ──────────────────────────────────────────────────────────────────

def auth_headers(config):
    return {
        'Authorization': f"Bearer {config['jwt_token']}",
        'X-Agent-Version': AGENT_VERSION,
    }


# ── Core logic ────────────────────────────────────────────────────────────────

def get_active_workday(config):
    resp = requests.get(
        f"{config['server_url'].rstrip('/')}/api/workday/active/",
        headers=auth_headers(config),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def capture_and_upload(config, workday_id):
    img = ImageGrab.grab()
    buf = BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=85, optimize=True)
    buf.seek(0)
    resp = requests.post(
        f"{config['server_url'].rstrip('/')}/api/screenshot/",
        headers=auth_headers(config),
        data={'workday_id': workday_id},
        files={'image': ('screenshot.jpg', buf, 'image/jpeg')},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def run():
    log.info('Agente iniciado.')

    threading.Thread(target=start_ping_server, daemon=True).start()
    log.info(f'Servidor de ping escuchando en 127.0.0.1:{PING_PORT}')

    threading.Thread(target=ws_thread, daemon=True).start()

    config = load_config()

    # Activación silenciosa con token pre-configurado (viene en el ZIP de descarga)
    if config.get('activation_token', '').strip() and not config.get('jwt_token', '').strip():
        log.info('Token de activación encontrado. Activando agente silenciosamente...')
        result = activate_with_token(config)
        if result:
            config = result
            log.info('Agente activado correctamente.')
        else:
            log.warning('Activación con token falló (token expirado o inválido). Intentando activación manual...')
            config['activation_token'] = ''
            save_config(config)

    # Fallback: si aún no hay JWT, abrir navegador para login con Nextcloud
    if needs_setup(config):
        config = run_setup(config)
        if not config:
            log.error('Activación fallida. Intenta ejecutar el agente de nuevo.')
            return

    POLL_ACTIVE   = 15 * 60   # máximo 15 min con jornada activa
    POLL_INACTIVE = 30 * 60   # cada 30 min sin jornada (solo para mantener heartbeat)
    POLL_ERROR    = 10 * 60   # reintento tras cualquier error
    last_capture_time = 0
    last_workday_id = None

    try:
        while True:
            global _force_capture
            poll_interval = POLL_INACTIVE
            try:
                config = load_config()

                data = get_active_workday(config)
                capture_interval = int(data.get('capture_interval_minutes') or config.get('capture_interval_minutes', 30)) * 60

                if data.get('active'):
                    workday_id = data['workday_id']
                    screenshots_enabled = data.get('screenshots_enabled', True)
                    now = time.time()
                    is_new_workday = (workday_id != last_workday_id)
                    time_since_last = now - last_capture_time
                    forced = _force_capture
                    _force_capture = False

                    if not screenshots_enabled:
                        log.info('Capturas deshabilitadas para este empleado. Omitiendo captura.')
                        last_workday_id = workday_id
                    elif forced or is_new_workday or time_since_last >= capture_interval:
                        if forced:
                            log.info('Captura forzada por el servidor.')
                        result = capture_and_upload(config, workday_id)
                        log.info(f"Captura enviada — screenshot_id={result.get('screenshot_id')}")
                        last_capture_time = now
                        last_workday_id = workday_id

                    poll_interval = min(POLL_ACTIVE, capture_interval)
                else:
                    log.debug('Sin jornada activa.')
                    last_workday_id = None

            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 401:
                    log.info('JWT expirado. Intentando renovar...')
                    result = refresh_jwt(config)
                    if result is NEEDS_REAUTH:
                        config['jwt_token'] = ''
                        config['refresh_token'] = ''
                        save_config(config)
                        config = run_setup(config)
                        if not config:
                            log.error('Re-autenticación fallida. El agente se detendrá.')
                            return
                    elif result is None:
                        poll_interval = POLL_ERROR
                    else:
                        config = result
                else:
                    log.error(f'HTTP error: {e}')
                    poll_interval = POLL_ERROR
            except Exception as e:
                log.error(f'Error inesperado: {e}')
                poll_interval = POLL_ERROR

            # Esperar en trozos de 1 s para que Ctrl+C interrumpa en Windows
            deadline = time.time() + poll_interval
            while time.time() < deadline:
                if _capture_event.wait(timeout=1):
                    break
            _capture_event.clear()

    except KeyboardInterrupt:
        log.info('Agente detenido por el usuario.')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if '--install' in sys.argv:
        install_startup()
    elif '--uninstall' in sys.argv:
        uninstall_startup()
    else:
        run()
