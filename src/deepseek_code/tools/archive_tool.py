"""Herramienta para crear, extraer y listar archivos ZIP."""

import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from ..server.tool import BaseTool
from ..security.sandbox import SecurePath

# Limites de seguridad
MAX_ARCHIVE_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_FILES_IN_ARCHIVE = 10000


class ArchiveTool(BaseTool):
    """Crea, extrae y lista archivos ZIP."""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="archive",
            description=(
                "Gestiona archivos ZIP. Acciones: "
                "'create' comprime archivos/directorios en un ZIP, "
                "'extract' descomprime un ZIP a un directorio, "
                "'list' muestra el contenido de un ZIP sin extraer."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "extract", "list"],
                    "description": (
                        "'create': comprime archivos/directorios en ZIP. "
                        "'extract': descomprime ZIP a directorio. "
                        "'list': muestra contenido del ZIP."
                    )
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Para create: ruta del archivo o directorio a comprimir. "
                        "Para extract/list: ruta del archivo ZIP."
                    )
                },
                "destination": {
                    "type": "string",
                    "description": (
                        "Para create: ruta del ZIP destino (ej: 'proyecto.zip'). "
                        "Para extract: directorio donde extraer (default: mismo dir del ZIP)."
                    )
                },
                "compression": {
                    "type": "string",
                    "enum": ["deflated", "stored"],
                    "description": "Tipo de compresion: 'deflated' (default, mas pequeno) o 'stored' (sin compresion, mas rapido).",
                    "default": "deflated"
                }
            },
            "required": ["action", "source"]
        }

    async def execute(self, action: str, source: str, destination: Optional[str] = None, compression: str = "deflated") -> str:
        if action == "create":
            return await self._create(source, destination, compression)
        elif action == "extract":
            return await self._extract(source, destination)
        elif action == "list":
            return await self._list(source)
        else:
            return f"Error: accion desconocida '{action}'. Usa: create, extract, list."

    async def _create(self, source: str, destination: Optional[str], compression: str) -> str:
        secure_src = SecurePath(source, self.allowed_paths)
        await secure_src.validate_read()
        src_path = secure_src.resolved_path

        if not src_path.exists():
            return f"Error: '{source}' no existe."

        # Determinar destino
        if destination:
            secure_dst = SecurePath(destination, self.allowed_paths)
            await secure_dst.validate_write()
            dst_path = secure_dst.resolved_path
        else:
            dst_path = src_path.with_suffix('.zip') if src_path.is_file() else src_path.parent / f"{src_path.name}.zip"

        if not dst_path.suffix == '.zip':
            dst_path = dst_path.with_suffix('.zip')

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        comp = zipfile.ZIP_DEFLATED if compression == "deflated" else zipfile.ZIP_STORED
        file_count = 0
        total_size = 0

        with zipfile.ZipFile(str(dst_path), 'w', compression=comp) as zf:
            if src_path.is_file():
                size = src_path.stat().st_size
                if size > MAX_ARCHIVE_SIZE:
                    return f"Error: archivo demasiado grande ({size / 1024 / 1024:.1f} MB). Limite: 500 MB."
                zf.write(str(src_path), src_path.name)
                file_count = 1
                total_size = size
            elif src_path.is_dir():
                for file in src_path.rglob('*'):
                    if file.is_file():
                        file_count += 1
                        if file_count > MAX_FILES_IN_ARCHIVE:
                            return f"Error: demasiados archivos (>{MAX_FILES_IN_ARCHIVE}). Reduce el directorio."
                        total_size += file.stat().st_size
                        if total_size > MAX_ARCHIVE_SIZE:
                            return f"Error: tamaño total excede 500 MB."
                        arcname = file.relative_to(src_path)
                        zf.write(str(file), str(arcname))

        zip_size = dst_path.stat().st_size
        ratio = (1 - zip_size / total_size) * 100 if total_size > 0 else 0
        return (
            f"ZIP creado: {dst_path}\n"
            f"  Archivos: {file_count}\n"
            f"  Tamaño original: {self._fmt_size(total_size)}\n"
            f"  Tamaño ZIP: {self._fmt_size(zip_size)} ({ratio:.1f}% compresion)"
        )

    async def _extract(self, source: str, destination: Optional[str]) -> str:
        secure_src = SecurePath(source, self.allowed_paths)
        await secure_src.validate_read()
        src_path = secure_src.resolved_path

        if not src_path.exists():
            return f"Error: '{source}' no existe."
        if not zipfile.is_zipfile(str(src_path)):
            return f"Error: '{source}' no es un archivo ZIP valido."

        if destination:
            secure_dst = SecurePath(destination, self.allowed_paths)
            await secure_dst.validate_write()
            dst_path = secure_dst.resolved_path
        else:
            dst_path = src_path.parent / src_path.stem

        dst_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(src_path), 'r') as zf:
            # Seguridad: verificar que no hay paths maliciosos (path traversal)
            for info in zf.infolist():
                if info.filename.startswith('/') or '..' in info.filename:
                    return f"Error: ZIP contiene rutas peligrosas (path traversal): {info.filename}"
            file_count = len(zf.infolist())
            zf.extractall(str(dst_path))

        return f"ZIP extraido: {dst_path} ({file_count} archivos)"

    async def _list(self, source: str) -> str:
        secure_src = SecurePath(source, self.allowed_paths)
        await secure_src.validate_read()
        src_path = secure_src.resolved_path

        if not src_path.exists():
            return f"Error: '{source}' no existe."
        if not zipfile.is_zipfile(str(src_path)):
            return f"Error: '{source}' no es un archivo ZIP valido."

        with zipfile.ZipFile(str(src_path), 'r') as zf:
            entries = zf.infolist()
            total_size = sum(e.file_size for e in entries)
            compressed = sum(e.compress_size for e in entries)

            lines = [f"Contenido de {src_path.name} ({len(entries)} archivos, {self._fmt_size(total_size)}):\n"]
            for entry in entries[:5000]:
                date = f"{entry.date_time[0]:04d}-{entry.date_time[1]:02d}-{entry.date_time[2]:02d}"
                lines.append(f"  {self._fmt_size(entry.file_size):>10}  {date}  {entry.filename}")

            if len(entries) > 5000:
                lines.append(f"\n  ... y {len(entries) - 5000} archivos mas")

        return "\n".join(lines)

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        else:
            return f"{size / 1024 / 1024 / 1024:.1f} GB"
