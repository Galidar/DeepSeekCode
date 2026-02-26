"""Herramientas para ejecutar comandos en el sistema"""

import asyncio
import shlex
import sys
import platform
from pathlib import Path
from typing import List, Optional
from ..server.tool import BaseTool
from ..security.sandbox import CommandValidator

class RunCommandTool(BaseTool):
    """Ejecuta comandos en el sistema con soporte nativo para Windows"""

    def __init__(self, allowed_commands: List[str], allowed_paths: Optional[List[str]] = None, timeout: int = 120):
        self.default_timeout = timeout
        self.validator = CommandValidator(allowed_commands)
        self.is_windows = platform.system() == "Windows"
        self.allowed_paths = [Path(p).expanduser().resolve() for p in (allowed_paths or [])]
        super().__init__(
            name="run_command",
            description=(
                "Ejecuta cualquier comando en el sistema operativo. "
                "Soporta argumentos con comillas (ej: python \"mi script.py\"). "
                "Timeout por defecto: 120s (maximo 300s). "
                "No permite encadenar con &&, ;, | (ejecuta cada comando por separado). "
                "Puedes ejecutar: dir, type, python, git, pip, npm, node, powershell, "
                "y cualquier otro programa instalado."
            )
        )

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Comando a ejecutar. Soporta argumentos con espacios entre comillas: "
                        "'python \"mi archivo.py\" --flag \"argumento con espacios\"'. "
                        "NO se permite encadenar comandos (&&, ;, |)."
                    )
                },
                "timeout": {
                    "type": "integer",
                    "description": "Tiempo maximo de ejecucion en segundos (default 120, maximo 600)",
                    "default": self.default_timeout,
                    "minimum": 1,
                    "maximum": 600
                },
                "working_dir": {
                    "type": "string",
                    "description": "Directorio de trabajo para ejecutar el comando (cualquier ruta valida)"
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, timeout: Optional[int] = None, working_dir: Optional[str] = None) -> dict:
        # Validar comando contra whitelist y operadores peligrosos
        if not self.validator.is_allowed(command):
            return {
                "error": f"Comando no permitido: {command}",
                "hint": "No se permiten operadores como &&, ;, |. Ejecuta cada comando por separado."
            }

        # Validar working_dir contra rutas permitidas
        if working_dir and self.allowed_paths:
            wd_path = Path(working_dir).expanduser().resolve()
            allowed = any(
                wd_path == ap or ap in wd_path.parents
                for ap in self.allowed_paths
            )
            if not allowed:
                return {"error": f"working_dir fuera de rutas permitidas: {working_dir}"}

        timeout = timeout or self.default_timeout

        try:
            # Parsear comando con shlex para manejar comillas correctamente
            if self.is_windows:
                try:
                    cmd_parts = shlex.split(command, posix=False)
                except ValueError as e:
                    return {"error": f"Error parseando comando (comillas incorrectas): {e}"}

                # En Windows, siempre usar cmd.exe /c para resolver .cmd/.bat
                # (npm, yarn, pip, etc. son scripts .cmd, no .exe)
                # Los operadores peligrosos ya estan bloqueados por CommandValidator
                full_cmd = ["cmd.exe", "/c"] + cmd_parts
            else:
                try:
                    full_cmd = shlex.split(command)
                except ValueError as e:
                    return {"error": f"Error parseando comando (comillas incorrectas): {e}"}

            # Ejecutar el proceso
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                limit=1024*1024
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "error": f"Comando excedio el tiempo limite de {timeout}s",
                    "command": command
                }

            return {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": process.returncode,
                "success": process.returncode == 0
            }

        except FileNotFoundError:
            return {"error": f"Comando no encontrado: {command}"}
        except Exception as e:
            return {"error": f"Error ejecutando comando: {str(e)}"}
