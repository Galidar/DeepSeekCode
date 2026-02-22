"""Herramientas para operaciones con el sistema de archivos (lectura, escritura, eliminacion, movimiento, copia)."""

import os
import aiofiles
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from ..server.tool import BaseTool
from ..security.sandbox import SecurePath

# Limite de tamaño de archivo para lectura (50 MB)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

class ReadFileTool(BaseTool):
    """Lee el contenido de un archivo de texto"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="read_file",
            description=(
                "Lee el contenido de un archivo de texto. "
                "Soporta lectura parcial con max_lines para archivos grandes. "
                "Limite de 50MB. No soporta archivos binarios."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del archivo a leer (absoluta o relativa a rutas permitidas)"
                },
                "encoding": {
                    "type": "string",
                    "description": "Codificacion del archivo (default utf-8). Usar 'latin-1' para archivos con caracteres especiales.",
                    "default": "utf-8"
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Numero maximo de lineas a leer. Util para archivos grandes.",
                    "minimum": 1
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, encoding: str = "utf-8", max_lines: Optional[int] = None) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_read()
        full_path = secure_path.resolved_path

        # Validar tamaño antes de leer
        file_size = full_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"Error: Archivo demasiado grande ({file_size / 1024 / 1024:.1f} MB). Limite: 50 MB."

        try:
            if max_lines:
                lines = []
                count = 0
                async with aiofiles.open(full_path, 'r', encoding=encoding) as f:
                    async for line in f:
                        if count >= max_lines:
                            break
                        lines.append(line)
                        count += 1
                result = ''.join(lines)
                if count >= max_lines:
                    result += f"\n... (truncado a {max_lines} lineas)"
                return result
            else:
                async with aiofiles.open(full_path, 'r', encoding=encoding) as f:
                    return await f.read()
        except UnicodeDecodeError:
            return f"Error: No se puede leer '{path}' como texto con codificacion '{encoding}'. Puede ser un archivo binario. Prueba con encoding='latin-1'."

class WriteFileTool(BaseTool):
    """Escribe contenido en un archivo (crea o sobrescribe, o añade al final)"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="write_file",
            description=(
                "Escribe contenido en un archivo. "
                "mode='overwrite' sobrescribe el archivo completo (default). "
                "mode='append' añade al final sin borrar lo existente. "
                "Crea directorios padres automaticamente."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del archivo a escribir"
                },
                "content": {
                    "type": "string",
                    "description": "Contenido a escribir en el archivo"
                },
                "encoding": {
                    "type": "string",
                    "description": "Codificacion del archivo (default utf-8)",
                    "default": "utf-8"
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "'overwrite' reemplaza todo el contenido (default), 'append' añade al final",
                    "default": "overwrite"
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "Crear directorios padres si no existen (default true)",
                    "default": True
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str, encoding: str = "utf-8", mode: str = "overwrite", create_parents: bool = True) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_write()
        full_path = secure_path.resolved_path

        if create_parents:
            full_path.parent.mkdir(parents=True, exist_ok=True)

        file_mode = 'a' if mode == 'append' else 'w'
        async with aiofiles.open(full_path, file_mode, encoding=encoding) as f:
            await f.write(content)

        bytes_written = len(content.encode(encoding))
        action = "añadido a" if mode == 'append' else "escrito en"
        return f"Archivo {action}: {full_path} ({bytes_written} bytes)"

class DeleteFileTool(BaseTool):
    """Elimina un archivo o directorio"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="delete_file",
            description=(
                "Elimina un archivo o directorio. "
                "Por defecto solo elimina archivos o directorios vacios. "
                "recursive=true ELIMINA PERMANENTEMENTE todo el arbol de directorios."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del archivo o directorio a eliminar"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Si true, elimina directorios con todo su contenido. IRREVERSIBLE.",
                    "default": False
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, recursive: bool = False) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_write()
        full_path = secure_path.resolved_path

        if not full_path.exists():
            return f"Error: {path} no existe"

        if full_path.is_file():
            size = full_path.stat().st_size
            full_path.unlink()
            return f"Archivo eliminado: {full_path} ({size} bytes)"
        elif full_path.is_dir():
            if recursive:
                total_files = sum(1 for _ in full_path.rglob('*') if _.is_file())
                total_dirs = sum(1 for _ in full_path.rglob('*') if _.is_dir())
                shutil.rmtree(full_path)
                return f"Directorio eliminado: {full_path} ({total_files} archivos, {total_dirs} subdirectorios)"
            else:
                try:
                    full_path.rmdir()
                    return f"Directorio vacio eliminado: {full_path}"
                except OSError:
                    items = list(full_path.iterdir())
                    return f"Error: El directorio tiene {len(items)} items. Usa recursive=true para eliminarlo."

class MoveFileTool(BaseTool):
    """Mueve o renombra un archivo o directorio"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="move_file",
            description=(
                "Mueve o renombra un archivo o directorio. "
                "Falla si el destino ya existe (usa delete_file primero). "
                "Crea directorios padres del destino automaticamente."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Ruta de origen (archivo o directorio)"
                },
                "destination": {
                    "type": "string",
                    "description": "Ruta de destino"
                }
            },
            "required": ["source", "destination"]
        }

    async def execute(self, source: str, destination: str) -> str:
        src_secure = SecurePath(source, self.allowed_paths)
        dst_secure = SecurePath(destination, self.allowed_paths)
        await src_secure.validate_read()
        await dst_secure.validate_write()

        src_path = src_secure.resolved_path
        dst_path = dst_secure.resolved_path

        if not src_path.exists():
            return f"Error: origen {source} no existe"

        if dst_path.exists():
            return f"Error: destino {destination} ya existe. Eliminalo primero con delete_file."

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src_path), str(dst_path))
        return f"Movido: {src_path} -> {dst_path}"

class CopyFileTool(BaseTool):
    """Copia un archivo o directorio"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="copy_file",
            description=(
                "Copia un archivo o directorio. "
                "Para directorios usa recursive=true. "
                "Si el destino ya existe, se fusiona el contenido."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Ruta de origen (archivo o directorio)"
                },
                "destination": {
                    "type": "string",
                    "description": "Ruta de destino"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Requerido para copiar directorios con su contenido",
                    "default": False
                }
            },
            "required": ["source", "destination"]
        }

    async def execute(self, source: str, destination: str, recursive: bool = False) -> str:
        src_secure = SecurePath(source, self.allowed_paths)
        dst_secure = SecurePath(destination, self.allowed_paths)
        await src_secure.validate_read()
        await dst_secure.validate_write()

        src_path = src_secure.resolved_path
        dst_path = dst_secure.resolved_path

        if not src_path.exists():
            return f"Error: origen {source} no existe"

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_file():
            shutil.copy2(str(src_path), str(dst_path))
            size = src_path.stat().st_size
            return f"Archivo copiado: {src_path} -> {dst_path} ({size} bytes)"
        elif src_path.is_dir():
            if recursive:
                total_files = sum(1 for _ in src_path.rglob('*') if _.is_file())
                shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=True)
                return f"Directorio copiado: {src_path} -> {dst_path} ({total_files} archivos)"
            else:
                return "Error: Para copiar directorios, usa recursive=true"

class ListDirectoryTool(BaseTool):
    """Lista el contenido de un directorio"""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="list_directory",
            description=(
                "Lista archivos y carpetas de un directorio. "
                "Muestra nombre, tamaño y opcionalmente fecha de modificacion. "
                "recursive=true para ver subdirectorios (limitado a max_results)."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del directorio a listar"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Listar subdirectorios recursivamente (default false)",
                    "default": False
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximo de items a listar (default 500). Util para directorios grandes.",
                    "default": 500,
                    "minimum": 1,
                    "maximum": 5000
                },
                "show_dates": {
                    "type": "boolean",
                    "description": "Mostrar fecha de ultima modificacion (default false)",
                    "default": False
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, recursive: bool = False, max_results: int = 500, show_dates: bool = False) -> str:
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_read()
        full_path = secure_path.resolved_path

        if not full_path.is_dir():
            return f"Error: {path} no es un directorio"

        if recursive:
            files = list(full_path.rglob("*"))
        else:
            files = list(full_path.iterdir())

        total_count = len(files)
        truncated = total_count > max_results
        files = sorted(files)[:max_results]

        result = []
        for f in files:
            rel_path = f.relative_to(full_path)
            try:
                stat = f.stat()
                if f.is_dir():
                    if show_dates:
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                        result.append(f"[DIR] {rel_path}/  ({mtime})")
                    else:
                        result.append(f"[DIR] {rel_path}/")
                else:
                    size = stat.st_size
                    if show_dates:
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                        result.append(f"      {rel_path}  ({size} bytes, {mtime})")
                    else:
                        result.append(f"      {rel_path}  ({size} bytes)")
            except (PermissionError, OSError):
                result.append(f"      {rel_path}  (sin acceso)")

        if truncated:
            result.append(f"\n... truncado: mostrando {max_results} de {total_count} items. Aumenta max_results si necesitas mas.")

        return "\n".join(result) if result else "(directorio vacio)"
