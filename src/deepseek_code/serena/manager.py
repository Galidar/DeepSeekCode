"""Gestor del ciclo de vida de Serena.

Controla inicio, descubrimiento de herramientas, registro/desregistro
en MCPServer, y parada del subproceso Serena.

Si serena-agent no esta instalado, registra herramientas nativas
(regex-based) como fallback automatico.
"""

import logging
import shutil
from typing import List, Optional, Tuple

from ..server.protocol import MCPServer
from .client import SerenaStdioClient
from .proxy_tool import SerenaProxyTool

logger = logging.getLogger(__name__)


class SerenaManager:
    """Gestor del ciclo de vida de Serena."""

    def __init__(
        self,
        mcp_server: MCPServer,
        deepseek_client,  # DeepSeekCodeClient (sin import circular)
        command: str = "serena-agent",
        project: Optional[str] = None,
        prefix: str = "serena_",
        allowed_paths: Optional[List[str]] = None,
    ):
        """
        Args:
            mcp_server: Servidor MCP donde registrar las herramientas
            deepseek_client: Cliente DeepSeek para invalidar cache de tools
            command: Comando para iniciar Serena
            project: Ruta al proyecto para activar en Serena
            prefix: Prefijo para nombres de herramientas (default: "serena_")
            allowed_paths: Rutas permitidas para herramientas nativas
        """
        self.mcp_server = mcp_server
        self.deepseek_client = deepseek_client
        self.serena_client = SerenaStdioClient(command)
        self.project = project
        self.prefix = prefix
        self.allowed_paths = allowed_paths or []
        self.registered_tools: List[str] = []
        self.using_native = False  # True si usamos fallback nativo

    async def start(self, project_override: Optional[str] = None) -> Tuple[bool, str]:
        """Inicia Serena y registra sus herramientas.

        Si serena-agent no esta disponible, registra herramientas nativas
        como fallback (SearchPatternTool, SymbolsOverviewTool, FindSymbolTool).

        Args:
            project_override: Ruta al proyecto (sobreescribe el de config)

        Returns:
            Tupla (exito, mensaje)
        """
        # Verificar que el comando existe
        cmd_parts = self.serena_client.command.split()
        cmd_name = cmd_parts[0]
        if not shutil.which(cmd_name):
            # Fallback: registrar herramientas nativas
            return self._register_native_fallback()

        # Iniciar subproceso externo
        started = await self.serena_client.start()
        if not started:
            # Si falla el inicio externo, usar fallback nativo
            logger.warning("Serena externa fallo al iniciar, usando fallback nativo")
            return self._register_native_fallback()

        # Activar proyecto si se especifico
        active_project = project_override or self.project
        if active_project:
            try:
                result = await self.serena_client.call_tool(
                    "activate_project",
                    {"project": active_project}
                )
                logger.info(f"Proyecto activado en Serena: {active_project}")
                self.project = active_project
            except Exception as e:
                logger.warning(f"No se pudo activar proyecto: {e}")

        # Descubrir herramientas
        tools = await self.serena_client.list_tools()
        if not tools:
            await self.serena_client.stop()
            # Sin herramientas externas, usar fallback
            return self._register_native_fallback()

        # Registrar cada herramienta como proxy en MCPServer
        registered_count = 0
        for tool_info in tools:
            try:
                proxy = SerenaProxyTool(
                    tool_info, self.serena_client, prefix=self.prefix
                )
                self.mcp_server.register_tool(proxy)
                self.registered_tools.append(proxy.name)
                registered_count += 1
            except Exception as e:
                logger.warning(f"Error registrando tool {tool_info.get('name')}: {e}")

        # Invalidar cache de tools en el cliente DeepSeek
        self.deepseek_client.invalidate_tools_cache()

        # Construir lista de nombres para el mensaje
        tool_names = [t.get("name", "?") for t in tools[:10]]
        extras = f" (+{len(tools) - 10} mas)" if len(tools) > 10 else ""

        msg = (
            f"Serena iniciada: {registered_count} herramientas registradas.\n"
            f"Herramientas: {', '.join(tool_names)}{extras}"
        )
        if active_project:
            msg += f"\nProyecto: {active_project}"

        return True, msg

    def _register_native_fallback(self) -> Tuple[bool, str]:
        """Registra herramientas nativas como fallback de Serena.

        Returns:
            Tupla (exito, mensaje)
        """
        from .native_tools import SearchPatternTool, SymbolsOverviewTool, FindSymbolTool

        native_tools = [
            SearchPatternTool(self.allowed_paths),
            SymbolsOverviewTool(self.allowed_paths),
            FindSymbolTool(self.allowed_paths),
        ]

        registered_count = 0
        for tool in native_tools:
            try:
                self.mcp_server.register_tool(tool)
                self.registered_tools.append(tool.name)
                registered_count += 1
            except Exception as e:
                logger.warning(f"Error registrando tool nativa {tool.name}: {e}")

        self.using_native = True
        self.deepseek_client.invalidate_tools_cache()

        tool_names = [t.name for t in native_tools]
        msg = (
            f"Serena nativa: {registered_count} herramientas registradas "
            f"(modo regex, sin serena-agent).\n"
            f"Herramientas: {', '.join(tool_names)}"
        )
        return True, msg

    async def stop(self) -> str:
        """Detiene Serena y desregistra todas sus herramientas.

        Returns:
            Mensaje de estado
        """
        # Si usamos modo nativo, solo desregistrar tools
        if self.using_native:
            removed = 0
            for tool_name in self.registered_tools:
                if self.mcp_server.unregister_tool(tool_name):
                    removed += 1
            self.registered_tools.clear()
            self.using_native = False
            self.deepseek_client.invalidate_tools_cache()
            return f"Serena nativa detenida. {removed} herramientas desregistradas."

        if not self.serena_client.is_running:
            return "Serena no esta en ejecucion."

        # Desregistrar herramientas del MCPServer
        removed = 0
        for tool_name in self.registered_tools:
            if self.mcp_server.unregister_tool(tool_name):
                removed += 1
        self.registered_tools.clear()

        # Detener subproceso
        await self.serena_client.stop()

        # Invalidar cache
        self.deepseek_client.invalidate_tools_cache()

        return f"Serena detenida. {removed} herramientas desregistradas."

    async def restart(self, project_override: Optional[str] = None) -> Tuple[bool, str]:
        """Reinicia Serena (stop + start).

        Returns:
            Tupla (exito, mensaje)
        """
        stop_msg = await self.stop()
        success, start_msg = await self.start(project_override)
        return success, f"{stop_msg}\n{start_msg}"

    def status(self) -> dict:
        """Retorna estado actual de Serena.

        Returns:
            Dict con running, tools_count, tools, project, mode
        """
        is_running = self.using_native or self.serena_client.is_running
        mode = "nativa" if self.using_native else "externa"
        return {
            "running": is_running,
            "mode": mode,
            "tools_count": len(self.registered_tools),
            "tools": self.registered_tools[:20],
            "project": self.project,
            "command": self.serena_client.command
        }
