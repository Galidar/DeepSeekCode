"""Herramientas para ejecutar comandos en el sistema"""

import asyncio
import shlex
import sys
import platform
from pathlib import Path
from typing import List, Optional
from ..server.tool import BaseTool
from ..security.sandbox import CommandValidator

# Almacen global de procesos en background (PID -> Process)
_background_processes = {}


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
                "y cualquier otro programa instalado. "
                "Usa background=true para servidores de desarrollo (npm run dev, vite, etc.) "
                "que corren indefinidamente. Retorna la salida inicial y el proceso sigue vivo."
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
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Si true, ejecuta el comando en background y retorna la salida inicial "
                        "sin esperar a que termine. Ideal para servidores de desarrollo "
                        "(npm run dev, vite, flask run, etc.) que corren indefinidamente. "
                        "El proceso sigue vivo despues de retornar."
                    ),
                    "default": False
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, timeout: Optional[int] = None,
                      working_dir: Optional[str] = None, background: bool = False) -> dict:
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

                full_cmd = ["cmd.exe", "/c"] + cmd_parts
            else:
                try:
                    full_cmd = shlex.split(command)
                except ValueError as e:
                    return {"error": f"Error parseando comando (comillas incorrectas): {e}"}

            # --- Modo background: arrancar y retornar salida inicial ---
            if background:
                return await self._execute_background(full_cmd, command, working_dir)

            # --- Modo normal: esperar a que termine ---
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

    async def _execute_background(self, full_cmd: list, command: str,
                                   working_dir: Optional[str] = None) -> dict:
        """Ejecuta un comando en background, captura salida inicial y retorna.

        El proceso sigue vivo despues de retornar. Ideal para dev servers.
        Espera hasta 8 segundos para capturar salida inicial (URLs, errores).
        """
        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            limit=1024*1024
        )

        # Capturar salida inicial durante ~8 segundos
        let_initial_output = []
        let_wait_seconds = 8

        async def _read_stream(stream, label):
            """Lee lineas del stream hasta timeout."""
            try:
                while True:
                    line = await asyncio.wait_for(stream.readline(), timeout=1.0)
                    if not line:
                        break
                    let_initial_output.append(line.decode('utf-8', errors='replace'))
            except asyncio.TimeoutError:
                pass  # normal — stream aun abierto
            except Exception:
                pass

        # Leer stdout y stderr en paralelo durante let_wait_seconds
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(process.stdout, "stdout"),
                    _read_stream(process.stderr, "stderr"),
                ),
                timeout=let_wait_seconds
            )
        except asyncio.TimeoutError:
            pass  # esperado — el proceso sigue corriendo

        # Verificar si el proceso murio inmediatamente (error de arranque)
        if process.returncode is not None:
            # Proceso ya termino — leer lo que quede
            let_remaining_out, let_remaining_err = await process.communicate()
            if let_remaining_out:
                let_initial_output.append(let_remaining_out.decode('utf-8', errors='replace'))
            if let_remaining_err:
                let_initial_output.append(let_remaining_err.decode('utf-8', errors='replace'))
            return {
                "stdout": "".join(let_initial_output),
                "stderr": "",
                "returncode": process.returncode,
                "success": False,
                "background": False,
                "error": "El proceso termino inmediatamente (no quedo en background)"
            }

        # Proceso sigue vivo — guardarlo
        let_pid = process.pid
        _background_processes[let_pid] = process

        let_output_text = "".join(let_initial_output)
        return {
            "stdout": let_output_text,
            "pid": let_pid,
            "background": True,
            "success": True,
            "message": f"Proceso ejecutandose en background (PID {let_pid}). La salida inicial se muestra arriba."
        }
