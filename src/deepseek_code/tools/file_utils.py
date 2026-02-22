"""Utilidades avanzadas de archivos: buscar, info detallada, crear directorios."""

import os
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from ..server.tool import BaseTool
from ..security.sandbox import SecurePath


class FindFilesTool(BaseTool):
    """Busca archivos por patron glob en un directorio."""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="find_files",
            description=(
                "Busca archivos por patron glob. Ejemplos: "
                "'*.py' (archivos Python), '**/*.txt' (recursivo), "
                "'report_202*' (patron parcial). "
                "Retorna rutas coincidentes con tamaño opcional."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directorio base donde buscar"
                },
                "pattern": {
                    "type": "string",
                    "description": (
                        "Patron glob. Ej: '*.py', '**/*.log', 'data_*.csv'. "
                        "Usa '**/' al inicio para buscar recursivamente."
                    )
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximo de resultados (default 200)",
                    "default": 200,
                    "minimum": 1,
                    "maximum": 5000
                },
                "include_size": {
                    "type": "boolean",
                    "description": "Incluir tamaño de cada archivo (default false)",
                    "default": False
                }
            },
            "required": ["path", "pattern"]
        }

    async def execute(self, path: str, pattern: str, max_results: int = 200, include_size: bool = False) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_read()
        base = secure_path.resolved_path

        if not base.is_dir():
            return f"Error: '{path}' no es un directorio."

        results = []
        count = 0
        for match in base.glob(pattern):
            count += 1
            if count > max_results:
                break
            try:
                rel = match.relative_to(base)
                if include_size and match.is_file():
                    size = match.stat().st_size
                    results.append(f"  {rel}  ({_fmt_size(size)})")
                else:
                    prefix = "[DIR] " if match.is_dir() else "      "
                    results.append(f"{prefix}{rel}")
            except (PermissionError, OSError):
                results.append(f"      {match.name}  (sin acceso)")

        truncated = count > max_results
        header = f"Busqueda: '{pattern}' en {base} — {min(count, max_results)} resultados"
        if truncated:
            header += f" (truncado, hay mas de {max_results})"

        if not results:
            return f"Sin resultados para '{pattern}' en {base}"

        return header + "\n" + "\n".join(results)


class FileInfoTool(BaseTool):
    """Muestra informacion detallada de un archivo o directorio."""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="file_info",
            description=(
                "Muestra info detallada de un archivo o directorio: "
                "tamaño, fechas, tipo MIME, numero de lineas (si es texto), "
                "y para directorios: cantidad de archivos y tamaño total."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del archivo o directorio"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_read()
        full_path = secure_path.resolved_path

        if not full_path.exists():
            return f"Error: '{path}' no existe."

        stat = full_path.stat()
        created = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        info = [f"Ruta: {full_path}"]

        if full_path.is_file():
            info.append(f"Tipo: archivo")
            info.append(f"Tamaño: {_fmt_size(stat.st_size)} ({stat.st_size:,} bytes)")
            info.append(f"Extension: {full_path.suffix or '(sin extension)'}")

            mime, _ = mimetypes.guess_type(str(full_path))
            info.append(f"Tipo MIME: {mime or 'desconocido'}")

            info.append(f"Creado: {created}")
            info.append(f"Modificado: {modified}")

            # Contar lineas si parece texto
            if mime and mime.startswith('text') or full_path.suffix in (
                '.py', '.js', '.ts', '.json', '.xml', '.html', '.css',
                '.md', '.txt', '.csv', '.yaml', '.yml', '.toml', '.cfg',
                '.ini', '.log', '.sh', '.bat', '.ps1', '.sql'
            ):
                try:
                    line_count = 0
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                        for _ in f:
                            line_count += 1
                    info.append(f"Lineas: {line_count:,}")
                except Exception:
                    pass

            # Permisos
            readable = os.access(full_path, os.R_OK)
            writable = os.access(full_path, os.W_OK)
            info.append(f"Permisos: {'lectura' if readable else ''}{'+escritura' if writable else ''}")

        elif full_path.is_dir():
            info.append(f"Tipo: directorio")
            info.append(f"Creado: {created}")
            info.append(f"Modificado: {modified}")

            # Contar contenido
            file_count = 0
            dir_count = 0
            total_size = 0
            try:
                for item in full_path.rglob('*'):
                    if item.is_file():
                        file_count += 1
                        try:
                            total_size += item.stat().st_size
                        except OSError:
                            pass
                    elif item.is_dir():
                        dir_count += 1
                info.append(f"Archivos: {file_count:,}")
                info.append(f"Subdirectorios: {dir_count:,}")
                info.append(f"Tamaño total: {_fmt_size(total_size)}")
            except PermissionError:
                info.append("(sin acceso completo para contar contenido)")

        elif full_path.is_symlink():
            info.append(f"Tipo: enlace simbolico")
            info.append(f"Apunta a: {full_path.resolve()}")

        return "\n".join(info)


class MakeDirectoryTool(BaseTool):
    """Crea directorios con estructura de padres."""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="make_directory",
            description=(
                "Crea un directorio. Crea automaticamente los directorios "
                "padres si no existen (como mkdir -p)."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del directorio a crear"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_write()
        full_path = secure_path.resolved_path

        if full_path.exists():
            if full_path.is_dir():
                return f"El directorio ya existe: {full_path}"
            else:
                return f"Error: ya existe un archivo con ese nombre: {full_path}"

        full_path.mkdir(parents=True, exist_ok=True)
        return f"Directorio creado: {full_path}"


def _fmt_size(size: int) -> str:
    """Formatea tamaño en bytes a formato legible."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    else:
        return f"{size / 1024 / 1024 / 1024:.1f} GB"
