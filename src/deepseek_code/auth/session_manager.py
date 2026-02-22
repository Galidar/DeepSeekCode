"""Gestor de ciclo de vida de sesion DeepSeek con auto-recovery.

Verifica la validez de la sesion antes de cada operacion,
intenta refresh automatico si el token expiro, y provee
hot-reload de credenciales sin reiniciar la app.
"""

import os
import time
import asyncio
from typing import Optional

from rich.console import Console

console = Console()

# Cache de health check: no re-verificar antes de este intervalo (segundos)
HEALTH_CHECK_CACHE_SECONDS = 300  # 5 minutos
# Maximo de fallos consecutivos antes de requerir login manual
MAX_CONSECUTIVE_FAILURES = 3
# Backoff base para reintentos (segundos)
RETRY_BACKOFF_BASE = 2


class SessionManager:
    """Gestiona el ciclo de vida de la sesion DeepSeek con auto-recovery.

    Funciona como intermediario entre el cliente y la sesion web,
    verificando validez y recuperandose de tokens expirados.
    """

    def __init__(self, config: dict, appdata_dir: str):
        self.config = config
        self.appdata_dir = appdata_dir
        self._session_valid: Optional[bool] = None  # None=no chequeado
        self._last_health_check: float = 0
        self._consecutive_failures: int = 0
        self._mode = self._detect_mode()

    def _detect_mode(self) -> str:
        """Detecta el modo actual de operacion."""
        if self.config.get("bearer_token") and self.config.get("cookies"):
            return "web"
        elif os.getenv("DEEPSEEK_API_KEY") or self.config.get("api_key"):
            return "api"
        return "none"

    @property
    def is_web_mode(self) -> bool:
        return self._mode == "web"

    async def ensure_valid_session(self) -> bool:
        """Verifica sesion antes de cada operacion. Auto-recovery si falla.

        Returns:
            True si la sesion es valida, False si necesita /login manual.
        """
        # API mode: siempre valido (la API key no expira frecuentemente)
        if not self.is_web_mode:
            return True

        # Cache: si ya verificamos recientemente, skip
        elapsed = time.time() - self._last_health_check
        if self._session_valid is True and elapsed < HEALTH_CHECK_CACHE_SECONDS:
            return True

        # Health check real
        try:
            result = await self.health_check()
            if result.get("valid"):
                self._session_valid = True
                self._consecutive_failures = 0
                return True
        except Exception:
            pass

        # Sesion invalida — intentar refresh
        self._session_valid = False
        self._consecutive_failures += 1

        if self._consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            # Intentar refresh con backoff
            backoff = RETRY_BACKOFF_BASE ** self._consecutive_failures
            await asyncio.sleep(min(backoff, 10))

            refreshed = await self.refresh_session()
            if refreshed:
                self._session_valid = True
                self._consecutive_failures = 0
                return True

        # Demasiados fallos — pedir login manual
        console.print(
            "[yellow]Sesion expirada. Ejecuta /login para renovar.[/yellow]"
        )
        return False

    async def refresh_session(self) -> bool:
        """Intenta re-validar la sesion sin abrir ventana Qt.

        Solo funciona si las cookies siguen siendo validas y solo
        el bearer token expiro. Si las cookies tambien expiraron,
        retorna False y se necesita login manual completo.
        """
        try:
            from cli.config_loader import load_config
            fresh_config = load_config()

            bearer = fresh_config.get("bearer_token")
            cookies = fresh_config.get("cookies")
            wasm_path = fresh_config.get("wasm_path", "")

            if not bearer or not cookies:
                return False

            # Intentar health check con credenciales frescas
            from deepseek_code.auth.web_login import validate_session
            valid = await asyncio.get_event_loop().run_in_executor(
                None, validate_session, bearer, cookies, wasm_path
            )

            if valid:
                self.config.update({
                    "bearer_token": bearer,
                    "cookies": cookies,
                })
                self._last_health_check = time.time()
                return True

            return False
        except Exception:
            return False

    async def health_check(self) -> dict:
        """Ejecuta health check: valida PoW sin enviar mensaje real.

        Returns:
            dict con keys: valid, mode, last_check, consecutive_failures
        """
        result = {
            "valid": False,
            "mode": self._mode,
            "last_check": time.time(),
            "consecutive_failures": self._consecutive_failures,
        }

        if not self.is_web_mode:
            # API mode: asumimos valido (no hay forma barata de verificar)
            result["valid"] = True
            self._last_health_check = time.time()
            return result

        try:
            bearer = self.config.get("bearer_token")
            cookies = self.config.get("cookies")
            wasm_path = self.config.get("wasm_path", "")

            if not bearer or not cookies:
                return result

            from deepseek_code.auth.web_login import validate_session
            valid = await asyncio.get_event_loop().run_in_executor(
                None, validate_session, bearer, cookies, wasm_path
            )

            result["valid"] = valid
            self._last_health_check = time.time()
            self._session_valid = valid
            return result
        except Exception as e:
            result["error"] = str(e)
            return result

    def hot_reload(self, new_config: dict):
        """Recarga credenciales sin reiniciar la app.

        Actualiza el config interno y resetea el estado de sesion
        para forzar un health check en la proxima operacion.
        """
        # Actualizar credenciales
        for key in ("bearer_token", "cookies", "api_key", "wasm_path"):
            if key in new_config:
                self.config[key] = new_config[key]

        # Resetear estado para forzar re-verificacion
        self._mode = self._detect_mode()
        self._session_valid = None
        self._last_health_check = 0
        self._consecutive_failures = 0

    def get_status(self) -> dict:
        """Retorna estado actual de la sesion para /health."""
        elapsed = time.time() - self._last_health_check if self._last_health_check else None
        return {
            "mode": self._mode,
            "valid": self._session_valid,
            "last_check_seconds_ago": round(elapsed) if elapsed else None,
            "consecutive_failures": self._consecutive_failures,
            "has_bearer": bool(self.config.get("bearer_token")),
            "has_cookies": bool(self.config.get("cookies")),
            "has_api_key": bool(
                os.getenv("DEEPSEEK_API_KEY") or self.config.get("api_key")
            ),
        }
