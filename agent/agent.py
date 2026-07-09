"""
RedLine GS — Agente de capturas de pantalla para Windows
Corre silenciosamente en segundo plano, sin interfaz gráfica.

v2.x: el agente se instala SIN configuración. Al abrir el dashboard de Skylog
en el navegador, éste detecta al agente por el puerto local y le envía un token
de emparejamiento (POST /pair). Recién entonces el agente sabe de qué empleado
se trata. Si pierde la sesión, vuelve a quedar "sin identidad" y el dashboard
lo re-empareja automáticamente — nunca depende de un config.json descargado.

Uso:
  redline_agent.exe           -- ejecutar normalmente
  redline_agent.exe --install -- agregar al inicio de Windows (HKCU, sin admin)
  redline_agent.exe --uninstall -- quitar del inicio de Windows
"""

import json
import os
import sys
import time
import logging
import threading
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

PRODUCTION_SERVER_URL = 'https://skylog.redlinegs.com'

DEFAULT_CONFIG = {
    'server_url': PRODUCTION_SERVER_URL if getattr(sys, 'frozen', False) else 'http://localhost:8000',
    'jwt_token': '',
    'refresh_token': '',
    'capture_interval_minutes': 30,
    'employee_name': '',
    'employee_email': '',
}

_config_lock = threading.Lock()


def load_config():
    with _config_lock:
        if not os.path.exists(CONFIG_PATH):
            _write_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        with open(CONFIG_PATH, encoding='utf-8') as f:
            config = json.load(f)
        # El exe compilado siempre usa el servidor de producción, ignorando lo que
        # haya en el config (evita configs de dev con localhost que se cuelan).
        if getattr(sys, 'frozen', False) and config.get('server_url') != PRODUCTION_SERVER_URL:
            config['server_url'] = PRODUCTION_SERVER_URL
            _write_config(config)
        return config


def save_config(config):
    with _config_lock:
        _write_config(config)


def _write_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def is_paired(config):
    return bool(config.get('jwt_token', '').strip())


# ── Emparejamiento (el dashboard envía el token via POST /pair) ──────────────

def pair_with_token(activation_token, server_url=None):
    """Intercambia el activation_token (recibido del dashboard) por JWT.
    Devuelve el config actualizado o None si falla."""
    config = load_config()
    if server_url and not getattr(sys, 'frozen', False):
        # En dev el dashboard puede indicar su propio server_url (localhost:8000)
        config['server_url'] = server_url.rstrip('/')
    base = config.get('server_url', '').rstrip('/')

    log.info('Emparejando agente con token enviado por el dashboard...')
    try:
        resp = requests.post(
            f"{base}/api/agent/activate/",
            json={'activation_token': activation_token},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            config['jwt_token'] = data['access']
            config['refresh_token'] = data['refresh']
            config['employee_name'] = data.get('employee_name', '')
            config['employee_email'] = data.get('employee_email', '')
            save_config(config)
            log.info(f"Agente emparejado con: {data.get('employee_name')} ({data.get('employee_email')})")
            return config
        log.error(f'Error en emparejamiento: {resp.status_code} {resp.text}')
    except Exception as e:
        log.error(f'Error conectando al servidor para emparejar: {e}')
    return None


def unpair():
    """Borra la identidad. El dashboard re-empareja en la próxima visita."""
    config = load_config()
    config['jwt_token'] = ''
    config['refresh_token'] = ''
    config['employee_name'] = ''
    config['employee_email'] = ''
    save_config(config)
    return config


NEEDS_REAUTH = object()  # centinela: refresh falló, hay que re-emparejar


def refresh_jwt(config):
    """Usa el refresh_token para obtener un nuevo access_token sin intervención del usuario.
    Devuelve el config actualizado, NEEDS_REAUTH si hay que re-emparejar, o None si es un
    error de red transitorio."""
    server_url = config.get('server_url', '').rstrip('/')
    refresh_token = config.get('refresh_token', '').strip()

    if not refresh_token:
        log.warning('Sin refresh_token. El agente queda a la espera de emparejamiento.')
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
            log.warning('Refresh token inválido o expirado. Esperando re-emparejamiento desde el dashboard.')
            return NEEDS_REAUTH
    except Exception as e:
        log.error(f'Error de red renovando JWT: {e}')
        return None  # error transitorio, reintentar en el próximo ciclo


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


# ── Servidor local (health check + emparejamiento desde el dashboard) ────────

PING_PORT = 7337

_capture_event = threading.Event()
_force_capture = False  # True cuando el trigger viene del servidor (bypass de intervalo)


def _allowed_origin(origin):
    if not origin:
        return None
    allowed = {PRODUCTION_SERVER_URL, 'http://localhost:8000', 'http://127.0.0.1:8000'}
    config_url = load_config().get('server_url', '').rstrip('/')
    if config_url:
        allowed.add(config_url)
    return origin if origin.rstrip('/') in allowed else None


class _LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/ping':
            config = load_config()
            body = json.dumps({
                'status': 'ok',
                'version': AGENT_VERSION,
                'paired': is_paired(config),
                'employee_email': config.get('employee_email', ''),
            }).encode()
            self._json(200, body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/trigger':
            _capture_event.set()  # despierta el loop principal
            self._json(200, b'{"status":"triggered"}')
        elif self.path == '/pair':
            self._handle_pair()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_pair(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            data = json.loads(self.rfile.read(length) or b'{}')
            token = (data.get('activation_token') or '').strip()
        except Exception:
            token = ''
        if not token:
            self._json(400, b'{"status":"error","error":"activation_token requerido"}')
            return
        result = pair_with_token(token, data.get('server_url'))
        if result:
            _capture_event.set()  # que el loop retome de inmediato con la nueva identidad
            body = json.dumps({
                'status': 'paired',
                'employee_name': result.get('employee_name', ''),
                'employee_email': result.get('employee_email', ''),
            }).encode()
            self._json(200, body)
        else:
            self._json(502, b'{"status":"error","error":"No se pudo activar con el servidor"}')

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
        # Solo el dashboard de Skylog puede hablar con el agente
        origin = _allowed_origin(self.headers.get('Origin'))
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
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
    log.info(f'Agente v{AGENT_VERSION} iniciado.')

    threading.Thread(target=start_ping_server, daemon=True).start()
    log.info(f'Servidor local escuchando en 127.0.0.1:{PING_PORT}')

    threading.Thread(target=ws_thread, daemon=True).start()

    config = load_config()
    if not is_paired(config):
        log.info('Agente sin identidad. Esperando emparejamiento desde el dashboard de Skylog...')

    POLL_ACTIVE   = 15 * 60   # máximo 15 min con jornada activa
    POLL_INACTIVE = 30 * 60   # cada 30 min sin jornada (solo para mantener heartbeat)
    POLL_ERROR    = 10 * 60   # reintento tras cualquier error
    POLL_UNPAIRED = 30        # sin identidad: solo re-chequear el config
    last_capture_time = 0
    last_workday_id = None

    try:
        while True:
            global _force_capture
            poll_interval = POLL_INACTIVE
            try:
                config = load_config()

                if not is_paired(config):
                    poll_interval = POLL_UNPAIRED
                    _force_capture = False
                else:
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
                        # Perdió la sesión: queda sin identidad y el dashboard
                        # lo re-empareja automáticamente en la próxima visita.
                        config = unpair()
                        log.info('Identidad descartada. Esperando re-emparejamiento desde el dashboard.')
                        poll_interval = POLL_UNPAIRED
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
