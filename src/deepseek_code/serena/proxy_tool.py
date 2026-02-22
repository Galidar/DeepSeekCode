"""Proxy que envuelve herramientas de Serena como BaseTool locales.

Cada herramienta descubierta en Serena se registra como un BaseTool
en el MCPServer local con prefijo 'serena_' para evitar colisiones.
"""

import logging
from typing import Any, Dict

from ..server.tool import BaseTool
from .client import SerenaStdioClient

logger = logging.getLogger(__name__)


class SerenaProxyTool(BaseTool):
    """Envuelve una herramienta de Serena como BaseTool local.

    Al registrarse en MCPServer, DeepSeek puede invocarla como cualquier
    otra herramienta local. La ejecucion se delega a Serena via stdio.
    """

    def __init__(self, tool_info: Dict, serena_client: SerenaStdioClient,
                 prefix: str = "serena_"):
        """
        Args:
            tool_info: Dict con name, description, inputSchema de la herramienta Serena
            serena_client: Cliente stdio conectado a Serena
            prefix: Prefijo para el nombre local (default: "serena_")
        """
        self._original_name = tool_info["name"]
        self._schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
        self._serena_client = serena_client

        # Nombre local: prefix + nombre original
        local_name = f"{prefix}{tool_info['name']}"
        # Descripcion con marca [Serena]
        local_desc = f"[Serena] {tool_info.get('description', 'Herramienta de Serena')}"

        super().__init__(name=local_name, description=local_desc)

    def _build_schema(self) -> Dict[str, Any]:
        """Retorna el schema de la herramienta tal como lo reporto Serena."""
        return self._schema

    async def execute(self, **kwargs) -> Any:
        """Delega la ejecucion a Serena via stdio.

        Args:
            **kwargs: Argumentos para la herramienta Serena

        Returns:
            Resultado de la herramienta o mensaje de error
        """
        if not self._serena_client.is_running:
            return {"error": "Serena no esta en ejecucion. Usa /serena start para iniciarla."}

        try:
            result = await self._serena_client.call_tool(self._original_name, kwargs)
            return result
        except Exception as e:
            logger.error(f"Error ejecutando {self._original_name} en Serena: {e}")
            return {"error": f"Error en Serena ({self._original_name}): {str(e)}"}
