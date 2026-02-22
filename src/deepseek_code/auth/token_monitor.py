"""Monitor periodico de salud de la sesion DeepSeek.

Corre como tarea asyncio en background, haciendo health checks
periodicos y emitiendo warnings si detecta problemas de sesion.
Nunca bloquea la operacion normal del usuario.
"""

import asyncio
import time
from typing import Optional, Callable

from rich.console import Console

console = Console()

# Intervalo por defecto entre health checks (segundos)
DEFAULT_CHECK_INTERVAL = 300  # 5 minutos
# Intervalo reducido cuando hay problemas detectados
ALERT_CHECK_INTERVAL = 60  # 1 minuto


class TokenMonitor:
    """Monitor periodico que verifica la salud de la sesion en background.

    Usa SessionManager.health_check() para validar la sesion
    periodicamente. Si detecta expiracion, imprime un warning
    pero nunca bloquea la operacion del usuario.
    """

    def __init__(
        self,
        session_manager,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        on_warning: Optional[Callable[[str], None]] = None,
    ):
        self.session_manager = session_manager
        self.check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._on_warning = on_warning or self._default_warning
        self._last_warning_time: float = 0
        self._warning_cooldown = 300  # No repetir warnings antes de 5 min
        self._checks_performed = 0
        self._warnings_emitted = 0

    @staticmethod
    def _default_warning(message: str):
        """Warning por defecto: imprime en consola."""
        console.print(f"\n  [yellow]{message}[/yellow]\n")

    async def start(self):
        """Inicia el monitor como tarea asyncio en background."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Detiene el monitor."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _monitor_loop(self):
        """Loop principal: health check periodico."""
        # Esperar un poco antes del primer check para no bloquear el inicio
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._do_check()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Fail-safe: nunca crashear el monitor

            # Intervalo adaptativo: mas frecuente si hay problemas
            interval = self.check_interval
            if self.session_manager._consecutive_failures > 0:
                interval = ALERT_CHECK_INTERVAL

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _do_check(self):
        """Ejecuta un health check y emite warning si hay problemas."""
        self._checks_performed += 1

        # Solo verificar en modo web (API no expira frecuentemente)
        if not self.session_manager.is_web_mode:
            return

        try:
            result = await self.session_manager.health_check()
        except Exception:
            result = {"valid": False}

        if not result.get("valid"):
            self._emit_warning(
                "Sesion web proxima a expirar o invalida. "
                "Usa /login si experimentas errores."
            )

    def _emit_warning(self, message: str):
        """Emite un warning respetando el cooldown."""
        now = time.time()
        if now - self._last_warning_time < self._warning_cooldown:
            return  # Cooldown activo, no repetir
        self._last_warning_time = now
        self._warnings_emitted += 1
        self._on_warning(message)

    def get_stats(self) -> dict:
        """Retorna estadisticas del monitor."""
        return {
            "running": self._running,
            "checks_performed": self._checks_performed,
            "warnings_emitted": self._warnings_emitted,
            "check_interval": self.check_interval,
        }
