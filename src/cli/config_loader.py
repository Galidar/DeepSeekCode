"""Carga y gestion de configuracion para DeepSeek-Code."""

import io
import os
import sys
import json
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar UnicodeEncodeError con emojis
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# --- Rutas globales ---
APPDATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'DeepSeek-Code')
os.makedirs(APPDATA_DIR, exist_ok=True)

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

SKILLS_DIR = os.path.join(BASE_DIR, 'skills')
os.makedirs(SKILLS_DIR, exist_ok=True)

# Ajustar sys.path para importaciones
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

VERSION = "1.0.0"


def load_config(config_path: str = None) -> dict:
    """Carga configuracion desde archivo JSON en APPDATA.

    Las credenciales sensibles (bearer_token, cookies, api_key) se
    descifran automaticamente si estan protegidas con DPAPI.
    Si el config tiene credenciales en texto plano, se re-guardan cifradas.
    """
    from .secure_config import load_config_secure, save_config_secure, SENSITIVE_FIELDS

    if config_path is None:
        config_path = os.path.join(APPDATA_DIR, 'config.json')

    default_config = {
        "allowed_paths": [],
        "allowed_commands": [],
        "model": "deepseek-chat",
        "max_tokens": 4096,
        "memory_path": os.path.join(APPDATA_DIR, 'memory.md'),
        "summary_threshold": 80,
        "skills_dir": SKILLS_DIR,
        "wasm_path": os.path.join(APPDATA_DIR, 'sha3_wasm_bg.wasm'),
        "bearer_token": None,
        "cookies": None,
        "api_key": None,
        "_config_path": config_path,
        "_appdata_dir": APPDATA_DIR,
        "lang": None,
        # DeepSeek V3.2: parametros avanzados (backward-compatible)
        "auto_select_model": True,       # Auto deepseek-reasoner para tareas complejas
        "thinking_enabled": True,        # Thinking mode en web session para codigo
        "pool_size": 5,                  # Max instancias paralelas (MultiSession)
        "chunk_threshold_tokens": 30000, # Umbral tokens para activar chunking
    }

    if os.path.exists(config_path):
        try:
            user_config = load_config_secure(config_path)
            # Detectar si hay credenciales en plaintext para migrar
            needs_reencrypt = False
            with open(config_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for field in SENSITIVE_FIELDS:
                val = raw.get(field)
                if val and isinstance(val, str) and not val.startswith("DPAPI:"):
                    needs_reencrypt = True
                elif val and isinstance(val, dict):
                    needs_reencrypt = True

            for k, v in user_config.items():
                if v is not None or k not in default_config:
                    default_config[k] = v

            # Migrar credenciales plaintext a DPAPI automaticamente
            if needs_reencrypt:
                try:
                    save_config_secure(default_config, config_path)
                    print("[config] Credenciales cifradas con DPAPI")
                except Exception:
                    pass

        except Exception as e:
            print(f"[config] Advertencia: No se pudo cargar ({e}). Usando defaults.")

    default_config["allowed_paths"] = [
        str(Path(p).expanduser().resolve()) for p in default_config["allowed_paths"]
    ]

    return default_config
