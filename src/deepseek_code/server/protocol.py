"""Implementación del protocolo MCP (Model Context Protocol)"""

import logging
from enum import Enum
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MCP_VERSION = "2025-03-26"

class MCPMethod(str, Enum):
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"
    LOGGING_NOTIFICATION = "notifications/logging"

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: MCPMethod
    params: Optional[Dict[str, Any]] = None

class MCPError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[str, int]
    result: Any

class MCPErrorResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    error: MCPError

class MCPServer:
    def __init__(self, name: str = "deepseek-code", version: str = "0.1.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, 'BaseTool'] = {}
        self.resources: Dict[str, 'BaseResource'] = {}
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(f"mcp.{self.name}")

    def register_tool(self, tool: 'BaseTool'):
        self.tools[tool.name] = tool
        self.logger.info(f"Tool registered: {tool.name}")

    def unregister_tool(self, tool_name: str) -> bool:
        """Desregistra una herramienta por nombre."""
        if tool_name in self.tools:
            del self.tools[tool_name]
            self.logger.info(f"Tool unregistered: {tool_name}")
            return True
        return False

    def register_resource(self, resource: 'BaseResource'):
        self.resources[resource.uri] = resource

    async def handle_request(self, request: MCPRequest) -> Union[MCPResponse, MCPErrorResponse]:
        try:
            if request.method == MCPMethod.TOOLS_LIST:
                return await self._handle_tools_list(request)
            elif request.method == MCPMethod.TOOLS_CALL:
                return await self._handle_tools_call(request)
            elif request.method == MCPMethod.RESOURCES_LIST:
                return await self._handle_resources_list(request)
            elif request.method == MCPMethod.RESOURCES_READ:
                return await self._handle_resources_read(request)
            else:
                return MCPErrorResponse(
                    id=request.id,
                    error=MCPError(code=-32601, message=f"Método no soportado: {request.method}")
                )
        except Exception as e:
            self.logger.exception("Error manejando request MCP")
            return MCPErrorResponse(
                id=getattr(request, 'id', None),
                error=MCPError(code=-32603, message=f"Error interno: {str(e)}")
            )

    async def _handle_tools_list(self, request: MCPRequest) -> MCPResponse:
        tools_list = [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema
            }
            for tool in self.tools.values()
        ]
        return MCPResponse(id=request.id, result={"tools": tools_list})

    async def _handle_tools_call(self, request: MCPRequest) -> MCPResponse:
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})

        if tool_name not in self.tools:
            return MCPErrorResponse(
                id=request.id,
                error=MCPError(code=-32602, message=f"Herramienta no encontrada: {tool_name}")
            )

        tool = self.tools[tool_name]
        result = await tool.execute(**arguments)
        return MCPResponse(id=request.id, result={"content": result})

    async def _handle_resources_list(self, request: MCPRequest) -> MCPResponse:
        resources_list = [
            {
                "uri": res.uri,
                "name": res.name,
                "description": res.description,
                "mimeType": res.mime_type
            }
            for res in self.resources.values()
        ]
        return MCPResponse(id=request.id, result={"resources": resources_list})

    async def _handle_resources_read(self, request: MCPRequest) -> MCPResponse:
        uri = request.params.get("uri")
        if uri not in self.resources:
            return MCPErrorResponse(
                id=request.id,
                error=MCPError(code=-32602, message=f"Recurso no encontrado: {uri}")
            )
        resource = self.resources[uri]
        content = await resource.read()
        return MCPResponse(
            id=request.id,
            result={
                "contents": [{
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": content
                }]
            }
        )

# Clase base para recursos (simplificada, no la usaremos mucho)
class BaseResource:
    def __init__(self, uri: str, name: str, description: str = "", mime_type: str = "text/plain"):
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type
    async def read(self) -> str:
        raise NotImplementedError