"""Modulo de produccion para login web en DeepSeek.

Captura cookies y bearer token automaticamente via PyQt5 WebEngine,
valida la sesion con un test PoW real, y guarda las credenciales en config.json.

Uso:
    from deepseek_code.auth.web_login import run_login, validate_session

    result = run_login("config.json", wasm_path="sha3_wasm_bg.wasm")
    # result = {"cookies": {...}, "bearer_token": "...", "validated": True}

Estrategia: genera un script Python autocontenido y lo ejecuta como
proceso independiente. Esto evita conflictos con Qt WebEngine que crashea
si se importa en cierto orden o desde multiprocessing.spawn.
"""

import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

# Verificar disponibilidad de PyQt5 sin importar Qt
try:
    import importlib.util
    PYQT_AVAILABLE = importlib.util.find_spec("PyQt5") is not None
except Exception:
    PYQT_AVAILABLE = False


def validate_session(bearer_token: str, cookies: dict, wasm_path: str) -> bool:
    """Valida una sesion web ejecutando get_challenge + solve_challenge.

    No envia mensaje real, solo verifica que el PoW funciona.
    Retorna True si la sesion es valida.
    """
    try:
        try:
            from ..client.deepseek_client import DeepSeekWebSession
        except (ImportError, ValueError):
            from deepseek_code.client.deepseek_client import DeepSeekWebSession
        session = DeepSeekWebSession(bearer_token, cookies, wasm_path)
        challenge = session.get_challenge()
        session.solve_challenge(challenge)
        return True
    except Exception:
        return False


WASM_URL = "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm"
WASM_SHA256 = "b3fca8cc072c1defbd60c02266a8e48bd307a1804aaff4314900aea720e72f7d"


def _download_wasm(dest_path: str) -> bool:
    """Descarga el archivo WASM desde DeepSeek y verifica su hash SHA-256."""
    try:
        import urllib.request
        import hashlib
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        urllib.request.urlretrieve(WASM_URL, dest_path)
        if not os.path.exists(dest_path):
            return False
        with open(dest_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        if file_hash != WASM_SHA256:
            os.remove(dest_path)
            return False
        return True
    except Exception:
        return False


def _find_wasm(config_path: str) -> Optional[str]:
    """Auto-detecta la ruta al archivo WASM. Si no existe, lo descarga."""
    appdata = os.path.join(
        os.environ.get('APPDATA', os.path.expanduser('~')), 'DeepSeek-Code'
    )
    appdata_wasm = os.path.join(appdata, "sha3_wasm_bg.wasm")
    candidates = [
        appdata_wasm,
        os.path.join(os.path.dirname(config_path), "sha3_wasm_bg.wasm"),
    ]
    project_dir = os.path.dirname(os.path.abspath(config_path))
    for root, _dirs, files in os.walk(project_dir):
        for f in files:
            if f.endswith(".wasm"):
                candidates.append(os.path.join(root, f))
        break  # Solo primer nivel
    for c in candidates:
        if os.path.exists(c):
            return c

    # No se encontro localmente — descargar a AppData
    if _download_wasm(appdata_wasm):
        return appdata_wasm
    return None


def _generate_login_script(config_path: str, wasm_path: str, result_file: str) -> str:
    """Genera el codigo Python del script de login autocontenido."""
    # Calcular src_path para imports de deepseek_code
    auth_dir = os.path.dirname(os.path.abspath(__file__))
    src_path = os.path.dirname(os.path.dirname(auth_dir))

    return f'''# -*- coding: utf-8 -*-
"""Script autocontenido de login DeepSeek. Generado por web_login.py."""
import sys, os, json
from pathlib import Path

sys.path.insert(0, {repr(src_path)})

# CRITICO: importar WebEngine ANTES de crear QApplication
import PyQt5.QtWebEngineWidgets  # noqa

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt5.QtCore import QUrl, QTimer, pyqtSignal, Qt
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage

BEARER_JS = """
(function() {{
    if (window.__bearerCaptured) return;
    window.__bearerCaptured = false;
    var origFetch = window.fetch;
    window.fetch = function(url, opts) {{
        if (opts && opts.headers && !window.__bearerCaptured) {{
            var auth = null;
            if (opts.headers instanceof Headers) {{
                auth = opts.headers.get('Authorization');
            }} else if (typeof opts.headers === 'object') {{
                auth = opts.headers['Authorization'] || opts.headers['authorization'];
            }}
            if (auth && auth.startsWith('Bearer ') && auth.length > 20) {{
                window.__bearerCaptured = true;
                console.log('__DSX_B:' + auth.substring(7));
            }}
        }}
        return origFetch.apply(this, arguments);
    }};
    var origOpen = XMLHttpRequest.prototype.open;
    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function() {{
        return origOpen.apply(this, arguments);
    }};
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {{
        if (!window.__bearerCaptured && name.toLowerCase() === 'authorization'
            && value.startsWith('Bearer ') && value.length > 20) {{
            window.__bearerCaptured = true;
            console.log('__DSX_B:' + value.substring(7));
        }}
        return origSetHeader.apply(this, arguments);
    }};
}})();
"""

class CapturePage(QWebEnginePage):
    cookies_captured = pyqtSignal(dict)
    bearer_captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cookies_done = False
        self._bearer_done = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._inject)
        self._timer.start(2000)

    def _inject(self):
        if not self._cookies_done:
            self.runJavaScript(
                "(function(){{ console.log('__DSX_C:' + document.cookie); }})();"
            )
        if not self._bearer_done:
            self.runJavaScript(BEARER_JS)
        if self._cookies_done and self._bearer_done:
            self._timer.stop()

    def javaScriptConsoleMessage(self, level, message, line, sourceID):
        if not self._cookies_done and message.startswith("__DSX_C:"):
            cookie_str = message[8:].strip()
            if cookie_str:
                cookies = {{}}
                for part in cookie_str.split(";"):
                    if "=" in part:
                        name, value = part.strip().split("=", 1)
                        cookies[name] = value
                if cookies:
                    self._cookies_done = True
                    self.cookies_captured.emit(cookies)
        if not self._bearer_done and message.startswith("__DSX_B:"):
            token = message[8:].strip()
            if token and len(token) > 10:
                self._bearer_done = True
                self.bearer_captured.emit(token)

# --- Estado global ---
config_path = {repr(config_path)}
wasm_path = {repr(wasm_path)}
result_file = {repr(result_file)}
result = {{"cookies": None, "bearer_token": None, "validated": False, "error": None}}
_cookies = None
_bearer = None
_elapsed_seconds = 0

def update_timer():
    global _elapsed_seconds
    _elapsed_seconds += 1
    if not _cookies or not _bearer:
        mins, secs = divmod(_elapsed_seconds, 60)
        time_str = f"{{mins}}:{{secs:02d}}"
        if not _cookies:
            status.setText(f"Esperando login... ({{time_str}}) - Inicia sesion y envia un mensaje")
        elif not _bearer:
            status.setText(f"Cookies OK - Envia un mensaje en el chat ({{time_str}})")

def on_cookies(cookies):
    global _cookies
    _cookies = cookies
    result["cookies"] = cookies
    status.setText("Cookies capturadas. Envia un mensaje para capturar token...")
    status.setStyleSheet(
        "font-size: 14px; padding: 8px; background: #0f3460; color: #e0e0e0;"
    )
    check_complete()

def on_bearer(token):
    global _bearer
    if _bearer:
        return
    _bearer = token
    result["bearer_token"] = token
    status.setText("Token capturado. Validando sesion...")
    status.setStyleSheet(
        "font-size: 14px; padding: 8px; background: #533483; color: #e0e0e0;"
    )
    check_complete()

def check_complete():
    if not _cookies or not _bearer:
        return
    save_config()
    if wasm_path and os.path.exists(wasm_path):
        try:
            from deepseek_code.client.deepseek_client import DeepSeekWebSession
            session = DeepSeekWebSession(_bearer, _cookies, wasm_path)
            challenge = session.get_challenge()
            session.solve_challenge(challenge)
            result["validated"] = True
            status.setText("Sesion valida! Cerrando en 2s...")
            status.setStyleSheet(
                "font-size: 14px; padding: 8px; background: #1a5c2a; color: #e0e0e0;"
            )
        except Exception as e:
            result["error"] = f"PoW fallo: {{e}}"
            status.setText("Credenciales guardadas (validacion PoW fallo)")
            status.setStyleSheet(
                "font-size: 14px; padding: 8px; background: #7a3030; color: #e0e0e0;"
            )
    else:
        result["error"] = "WASM no disponible"
        status.setText("Credenciales guardadas (sin WASM)")
    QTimer.singleShot(1500, finish)

def save_config():
    config = {{}}
    p = Path(config_path)
    if p.exists():
        try:
            config = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            config = {{}}
    config["cookies"] = _cookies
    config["bearer_token"] = _bearer
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, indent=4), encoding="utf-8")

def finish():
    save_result()
    app.quit()

def save_result():
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f)

# --- Main ---
app = QApplication(sys.argv)
app.aboutToQuit.connect(save_result)
win = QMainWindow()
win.setWindowTitle("DeepSeek Code - Iniciar Sesion")
win.setGeometry(100, 100, 1024, 768)
central = QWidget()
win.setCentralWidget(central)
layout = QVBoxLayout(central)
layout.setContentsMargins(0, 0, 0, 0)
layout.setSpacing(0)
status = QLabel("Inicia sesion y envia un mensaje en el chat...")
status.setStyleSheet(
    "font-size: 14px; padding: 10px; background: #1a1a2e; color: #e0e0e0;"
)
status.setAlignment(Qt.AlignCenter)
layout.addWidget(status)
browser = QWebEngineView()
page = CapturePage(browser)
browser.setPage(page)
layout.addWidget(browser)
page.cookies_captured.connect(on_cookies)
page.bearer_captured.connect(on_bearer)
# Timer de conteo visible
tick_timer = QTimer()
tick_timer.timeout.connect(update_timer)
tick_timer.start(1000)
browser.setUrl(QUrl("https://chat.deepseek.com"))
win.show()
app.exec_()
'''


def run_login(
    config_path: str,
    wasm_path: Optional[str] = None,
    timeout: int = 300,
) -> dict:
    """Abre ventana de login, captura credenciales y valida la sesion.

    Genera un script Python autocontenido y lo ejecuta como proceso
    independiente para evitar conflictos con Qt WebEngine.

    Args:
        config_path: Ruta al archivo config.json
        wasm_path: Ruta al archivo WASM para validacion PoW (opcional)
        timeout: Timeout en segundos (default 5 minutos)

    Returns:
        dict con keys: cookies, bearer_token, validated, error
    """
    if not PYQT_AVAILABLE:
        return {
            "cookies": None,
            "bearer_token": None,
            "validated": False,
            "error": "PyQt5 no disponible. Instala: pip install PyQt5 PyQtWebEngine",
        }

    if not wasm_path:
        wasm_path = _find_wasm(config_path) or ""

    result_file = os.path.join(tempfile.gettempdir(), "deepseek_login_result.json")
    script_file = os.path.join(tempfile.gettempdir(), "deepseek_login_script.py")

    # Limpiar resultado anterior
    if os.path.exists(result_file):
        os.remove(result_file)

    # Generar y escribir script
    script = _generate_login_script(config_path, wasm_path, result_file)
    with open(script_file, 'w', encoding='utf-8') as f:
        f.write(script)

    # Encontrar intérprete Python real (sys.executable apunta al .exe cuando estamos frozen)
    if getattr(sys, 'frozen', False):
        # Buscar python en el PATH del sistema
        import shutil
        python_exe = shutil.which('python') or shutil.which('python3') or 'python'
    else:
        python_exe = sys.executable

    # Ejecutar como proceso independiente
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
    try:
        proc = subprocess.Popen(
            [python_exe, script_file],
            creationflags=creationflags,
        )
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return {
            "cookies": None,
            "bearer_token": None,
            "validated": False,
            "error": "Timeout esperando login",
        }

    # Leer resultado
    if os.path.exists(result_file):
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            return result
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "cookies": None,
        "bearer_token": None,
        "validated": False,
        "error": "Proceso termino sin resultado",
    }
