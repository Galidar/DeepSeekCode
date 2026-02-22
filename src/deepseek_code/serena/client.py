"""Cliente JSON-RPC 2.0 para comunicarse con Serena via stdio.

Serena se ejecuta como subproceso independiente. La comunicacion es via
stdin/stdout con mensajes JSON-RPC delimitados por linea.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Timeout por defecto para operaciones Serena (segundos)
DEFAULT_TIMEOUT = 60
# Timeout para inicializacion (puede tardar mas)
INIT_TIMEOUT = 30


class SerenaStdioClient:
    """Cliente JSON-RPC 2.0 para comunicarse con Serena via stdio."""

    def __init__(self, command: str = "serena-agent"):
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def start(self) -> bool:
        """Inicia el subproceso Serena.

        Retorna True si el proceso inicio correctamente.
        """
        if self.is_running:
            logger.warning("Serena ya esta en ejecucion")
            return True

        try:
            # Separar comando en partes para evitar shell injection
            parts = self.command.split()
            self.process = await asyncio.create_subprocess_exec(
                *parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(f"Serena iniciada (PID: {self.process.pid})")

            # Esperar a que Serena este lista leyendo su mensaje de inicializacion
            ready = await self._wait_for_ready()
            if not ready:
                logger.error("Serena no respondio durante inicializacion")
                await self.stop()
                return False

            return True

        except FileNotFoundError:
            logger.error(f"Comando no encontrado: {self.command}")
            return False
        except Exception as e:
            logger.error(f"Error iniciando Serena: {e}")
            return False

    async def _wait_for_ready(self) -> bool:
        """Espera a que Serena envie su mensaje de inicializacion."""
        try:
            result = await self.send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "deepseek-code", "version": "1.0.0"}
                },
                timeout=INIT_TIMEOUT
            )
            if result is not None:
                logger.info("Serena lista para recibir comandos")
                await self._send_notification("notifications/initialized")
                return True
            return False
        except Exception as e:
            logger.error(f"Error esperando inicializacion de Serena: {e}")
            return False

    async def stop(self):
        """Detiene el subproceso Serena limpiamente."""
        if not self.process:
            return

        try:
            if self.process.stdin and not self.process.stdin.is_closing():
                self.process.stdin.close()

            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.process.kill()

            logger.info("Serena detenida")
        except Exception as e:
            logger.error(f"Error deteniendo Serena: {e}")
        finally:
            self.process = None

    async def send_request(self, method: str, params: Optional[Dict] = None,
                           timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Envia request JSON-RPC y espera respuesta.

        Args:
            method: Metodo JSON-RPC (ej: "tools/list", "tools/call")
            params: Parametros del request
            timeout: Timeout en segundos

        Returns:
            El campo 'result' de la respuesta, o None si hay error.
        """
        if not self.is_running:
            raise RuntimeError("Serena no esta en ejecucion")

        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
            }
            if params is not None:
                request["params"] = params

            line = json.dumps(request) + "\n"
            self.process.stdin.write(line.encode("utf-8"))
            await self.process.stdin.drain()

            try:
                raw = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"Timeout esperando respuesta de Serena ({method})")
                return None

            if not raw:
                logger.error("Serena cerro stdout inesperadamente")
                return None

            try:
                response = json.loads(raw.decode("utf-8").strip())
            except json.JSONDecodeError as e:
                logger.error(f"Respuesta JSON invalida de Serena: {e}")
                return None

            if "error" in response:
                err = response["error"]
                logger.error(f"Error de Serena: [{err.get('code')}] {err.get('message')}")
                return None

            return response.get("result")

    async def _send_notification(self, method: str, params: Optional[Dict] = None):
        """Envia una notificacion (sin id, sin respuesta esperada)."""
        if not self.is_running:
            return

        notification = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params

        line = json.dumps(notification) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

    async def list_tools(self) -> List[Dict]:
        """Obtiene lista de herramientas disponibles en Serena.

        Retorna lista de dicts con: name, description, inputSchema
        """
        result = await self.send_request("tools/list")
        if result and "tools" in result:
            return result["tools"]
        return []

    async def call_tool(self, name: str, arguments: Dict) -> Any:
        """Ejecuta una herramienta de Serena.

        Args:
            name: Nombre de la herramienta en Serena
            arguments: Argumentos para la herramienta

        Returns:
            Resultado de la herramienta
        """
        result = await self.send_request(
            "tools/call",
            {"name": name, "arguments": arguments}
        )
        if result is None:
            return {"error": f"Error ejecutando herramienta Serena: {name}"}

        # Extraer contenido de la respuesta MCP estandar
        content = result.get("content", [])
        if isinstance(content, list) and len(content) > 0:
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else str(content)
        return str(result)

    @property
    def is_running(self) -> bool:
        """Verifica si el subproceso Serena esta activo."""
        return self.process is not None and self.process.returncode is None
