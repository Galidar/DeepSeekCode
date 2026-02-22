"""Módulo de seguridad: sandboxing, permisos y rate limiting"""

import os
import sys
import shlex
from pathlib import Path
from typing import List, Optional
import time
import fnmatch
import asyncio

class SecurityError(Exception):
    pass

class SecurePath:
    """Validador de rutas. Si allowed_paths esta vacio, permite acceso total."""

    def __init__(self, requested_path: str, allowed_paths: List[Path]):
        self.requested = Path(requested_path).expanduser()
        self.allowed = allowed_paths
        self.unrestricted = len(allowed_paths) == 0
        self.resolved_path = self._resolve()

    def _resolve(self) -> Path:
        try:
            if not self.requested.is_absolute():
                if self.unrestricted:
                    # Sin restriccion: resolver relativo al CWD
                    return (Path.cwd() / self.requested).resolve()
                for base in self.allowed:
                    candidate = base / self.requested
                    if candidate.exists() or candidate.parent.exists():
                        return candidate.resolve()
                raise SecurityError(f"Ruta relativa no permitida: {self.requested}")
            return self.requested.resolve()
        except SecurityError:
            raise
        except Exception as e:
            raise SecurityError(f"Error resolviendo ruta: {e}")

    def _is_within_allowed(self) -> bool:
        if self.unrestricted:
            return True
        try:
            for allowed in self.allowed:
                if self.resolved_path == allowed or allowed in self.resolved_path.parents:
                    return True
            return False
        except Exception:
            return False

    async def validate_read(self):
        if not self._is_within_allowed():
            raise SecurityError(f"Acceso denegado: {self.requested} no esta en rutas permitidas")
        if not self.resolved_path.exists():
            raise SecurityError(f"El archivo no existe: {self.requested}")
        if not os.access(self.resolved_path, os.R_OK):
            raise SecurityError(f"Permiso de lectura denegado: {self.requested}")

    async def validate_write(self):
        if not self._is_within_allowed():
            raise SecurityError(f"Acceso denegado: {self.requested} no esta en rutas permitidas")
        if self.resolved_path.exists() and not os.access(self.resolved_path, os.W_OK):
            raise SecurityError(f"Permiso de escritura denegado: {self.requested}")
        parent = self.resolved_path.parent
        if not parent.exists():
            raise SecurityError(f"El directorio padre no existe: {parent}")
        if not os.access(parent, os.W_OK):
            raise SecurityError(f"No se puede escribir en el directorio: {parent}")

class CommandValidator:
    """Valida comandos contra una whitelist.
    Si allowed_commands esta vacio, permite TODOS los comandos.
    Siempre rechaza operadores de chaining para prevenir command injection."""

    # Operadores de shell que permiten encadenar comandos
    DANGEROUS_OPERATORS = ['&&', '||', ';', '|', '>', '>>', '<', '`', '$(']

    def __init__(self, allowed_commands: List[str]):
        self.allowed_commands = set(allowed_commands)
        self.allowed_patterns = [c for c in allowed_commands if '*' in c]
        self.unrestricted = len(allowed_commands) == 0

    def _has_dangerous_operators(self, command_line: str) -> bool:
        """Detecta operadores de shell peligrosos que permiten command injection."""
        for op in self.DANGEROUS_OPERATORS:
            if op in command_line:
                return True
        return False

    def is_allowed(self, command_line: str) -> bool:
        if not command_line or not command_line.strip():
            return False

        # Siempre rechazar operadores de chaining/redireccion (seguridad basica)
        if self._has_dangerous_operators(command_line):
            return False

        # Si no hay whitelist, permitir todo
        if self.unrestricted:
            return True

        try:
            parts = shlex.split(command_line)
        except ValueError:
            return False

        if not parts:
            return False

        cmd = parts[0]
        if cmd in self.allowed_commands:
            return True
        for pattern in self.allowed_patterns:
            if fnmatch.fnmatch(cmd, pattern):
                return True
        return False

class RateLimiter:
    def __init__(self, max_calls: int = 10, per_seconds: int = 60):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.calls: List[float] = []

    async def wait_if_needed(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.per_seconds]
        if len(self.calls) >= self.max_calls:
            sleep_time = self.per_seconds - (now - self.calls[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            await self.wait_if_needed()
        self.calls.append(now)
