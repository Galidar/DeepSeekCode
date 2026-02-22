"""Utilidades para el sistema quantum de delegacion paralela.

Crea MCPServer compartido y clientes independientes para DualSession.
Extrae logica de DeepSeekCodeApp.__init__() y _create_client() para reusar
sin instanciar la app completa.
"""

import os
import sys
from typing import List, Optional

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR
from deepseek_code.server.protocol import MCPServer
from deepseek_code.client.deepseek_client import DeepSeekCodeClient


def create_shared_mcp_server(config: dict) -> MCPServer:
    """Crea un MCPServer con todas las herramientas registradas.

    Replica la logica de DeepSeekCodeApp.__init__() pero retorna
    solo el MCPServer, sin crear clientes ni iniciar UI.

    Args:
        config: Configuracion cargada

    Returns:
        MCPServer listo para uso compartido
    """
    from deepseek_code.tools.filesystem import (
        ReadFileTool, WriteFileTool, ListDirectoryTool,
        DeleteFileTool, MoveFileTool, CopyFileTool,
    )
    from deepseek_code.tools.file_editor import EditFileTool
    from deepseek_code.tools.shell import RunCommandTool
    from deepseek_code.tools.memory_tool import MemoryTool
    from deepseek_code.tools.archive_tool import ArchiveTool
    from deepseek_code.tools.file_utils import FindFilesTool, FileInfoTool, MakeDirectoryTool

    mcp = MCPServer(name="deepseek-code-quantum")
    allowed_paths = config.get("allowed_paths", [])

    mcp.register_tool(ReadFileTool(allowed_paths))
    mcp.register_tool(WriteFileTool(allowed_paths))
    mcp.register_tool(ListDirectoryTool(allowed_paths))
    mcp.register_tool(DeleteFileTool(allowed_paths))
    mcp.register_tool(MoveFileTool(allowed_paths))
    mcp.register_tool(CopyFileTool(allowed_paths))
    mcp.register_tool(EditFileTool(allowed_paths))
    mcp.register_tool(ArchiveTool(allowed_paths))
    mcp.register_tool(FindFilesTool(allowed_paths))
    mcp.register_tool(FileInfoTool(allowed_paths))
    mcp.register_tool(MakeDirectoryTool(allowed_paths))

    allowed_commands = config.get("allowed_commands", [])
    mcp.register_tool(RunCommandTool(allowed_commands, allowed_paths=allowed_paths))

    memory_path = config.get("memory_path", os.path.join(APPDATA_DIR, 'memory.md'))
    mcp.register_tool(MemoryTool(memory_path))

    return mcp


def create_client_from_config(
    config: dict,
    mcp_server: MCPServer,
    label: str = "",
) -> DeepSeekCodeClient:
    """Crea un DeepSeekCodeClient independiente compartiendo MCPServer.

    Replica la logica de DeepSeekCodeApp._create_client() pero sin
    el ManageKeysTool (no necesario para quantum) y sin output a console.

    Args:
        config: Configuracion cargada
        mcp_server: MCPServer compartido
        label: Etiqueta para logs (ej: "A", "B")

    Returns:
        DeepSeekCodeClient configurado

    Raises:
        ValueError: Si no hay credenciales
    """
    bearer_token = config.get("bearer_token")
    cookies = config.get("cookies")
    api_key = os.getenv("DEEPSEEK_API_KEY") or config.get("api_key")
    wasm_path = config.get("wasm_path", os.path.join(APPDATA_DIR, "sha3_wasm_bg.wasm"))
    skills_dir = config.get("skills_dir", SKILLS_DIR)

    suffix = f" [{label}]" if label else ""

    if bearer_token and cookies:
        # Auto-descargar WASM si falta
        if not os.path.exists(wasm_path):
            print(f"  Descargando WASM{suffix}...", file=sys.stderr)
            from deepseek_code.auth.web_login import _download_wasm
            if not _download_wasm(wasm_path):
                raise FileNotFoundError("No se pudo descargar el WASM.")
        print(f"  Cliente web{suffix} creado", file=sys.stderr)
        return DeepSeekCodeClient(
            bearer_token=bearer_token,
            cookies=cookies,
            wasm_path=wasm_path,
            mcp_server=mcp_server,
            memory_path=config.get("memory_path"),
            summary_threshold=config.get("summary_threshold", 80),
            skills_dir=skills_dir,
            config=config,
        )
    elif api_key:
        print(f"  Cliente API{suffix} creado", file=sys.stderr)
        return DeepSeekCodeClient(
            api_key=api_key,
            mcp_server=mcp_server,
            memory_path=config.get("memory_path"),
            summary_threshold=config.get("summary_threshold", 80),
            skills_dir=skills_dir,
            config=config,
        )
    else:
        raise ValueError("No se encontraron credenciales para crear cliente quantum.")


def create_pool_clients(
    config: dict,
    mcp_server: MCPServer,
    pool_size: Optional[int] = None,
) -> List[DeepSeekCodeClient]:
    """Crea N clientes independientes compartiendo un MCPServer.

    Escala el quantum de 2 instancias fijas a N configurable.
    Cada cliente tiene su propia sesion web/API pero comparte herramientas.

    Args:
        config: Configuracion cargada
        mcp_server: MCPServer compartido (asyncio-safe)
        pool_size: Numero de clientes. Default: config["pool_size"] o 5

    Returns:
        Lista de DeepSeekCodeClient listos para MultiSession
    """
    n = pool_size or config.get("pool_size", 5)
    n = max(2, min(10, n))  # Clamp: minimo 2, maximo 10
    clients = []
    for i in range(n):
        label = f"P{i}"
        client = create_client_from_config(config, mcp_server, label)
        clients.append(client)
    print(f"  [pool] {n} clientes creados", file=sys.stderr)
    return clients
