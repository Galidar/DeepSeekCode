"""Herramienta para edicion avanzada de archivos: reemplazar, insertar, eliminar lineas."""

import os
import aiofiles
from pathlib import Path
from typing import Optional, List, Dict, Any
from ..server.tool import BaseTool
from ..security.sandbox import SecurePath

# Limite para mostrar contenido en el resultado (10 KB)
MAX_DISPLAY_SIZE = 10240

class EditFileTool(BaseTool):
    """Permite editar un archivo existente con operaciones precisas."""

    def __init__(self, allowed_paths: List[str]):
        super().__init__(
            name="edit_file",
            description=(
                "Edita un archivo con operaciones precisas: "
                "replace (reemplaza texto, por defecto solo la primera ocurrencia), "
                "insert (inserta lineas en una posicion), "
                "delete (elimina lineas). "
                "Se pueden aplicar multiples operaciones en orden."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del archivo a editar"
                },
                "operations": {
                    "type": "array",
                    "description": "Lista de operaciones a aplicar secuencialmente",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["replace", "insert", "delete"],
                                "description": (
                                    "'replace': busca old_text y lo reemplaza por new_text. "
                                    "'insert': inserta new_text en la linea indicada. "
                                    "'delete': elimina lineas desde la posicion indicada."
                                )
                            },
                            "old_text": {
                                "type": "string",
                                "description": "Texto a buscar y reemplazar (solo para op='replace')"
                            },
                            "new_text": {
                                "type": "string",
                                "description": "Texto nuevo (para replace: reemplazo; para insert: texto a insertar)"
                            },
                            "line": {
                                "type": "integer",
                                "description": "Numero de linea (1-based). Para insert: donde insertar. Para delete: desde donde eliminar."
                            },
                            "count": {
                                "type": "integer",
                                "description": "Numero de lineas a eliminar (solo para delete, default 1)",
                                "minimum": 1
                            },
                            "max_replacements": {
                                "type": "integer",
                                "description": "Maximo de reemplazos a realizar (solo para replace, default 1). Usa -1 para reemplazar todos.",
                                "default": 1
                            }
                        },
                        "required": ["op"]
                    }
                }
            },
            "required": ["path", "operations"]
        }

    async def execute(self, path: str, operations: List[Dict[str, Any]]) -> str:
        # Validar ruta
        secure_path = SecurePath(path, self.allowed_paths)
        await secure_path.validate_read()
        await secure_path.validate_write()
        full_path = secure_path.resolved_path

        # Leer el archivo original
        try:
            async with aiofiles.open(full_path, 'r', encoding='utf-8') as f:
                content = await f.read()
        except UnicodeDecodeError:
            return f"Error: No se puede leer '{path}' como texto UTF-8."

        # Aplicar operaciones una por una
        lines = content.splitlines(keepends=True)
        applied = []

        for i, op in enumerate(operations):
            op_type = op.get("op")

            if op_type == "replace":
                old = op.get("old_text")
                new = op.get("new_text", "")
                max_repl = op.get("max_replacements", 1)

                if old is None:
                    return f"Error en operacion {i+1}: replace requiere 'old_text'"
                if old not in content:
                    preview = old[:300] + '...' if len(old) > 300 else old
                    return f"Error en operacion {i+1}: texto no encontrado: '{preview}'"

                occurrences = content.count(old)
                if max_repl == -1:
                    content = content.replace(old, new)
                    applied.append(f"replace: {occurrences} ocurrencia(s)")
                else:
                    content = content.replace(old, new, max_repl)
                    applied.append(f"replace: {min(max_repl, occurrences)} de {occurrences} ocurrencia(s)")

                lines = content.splitlines(keepends=True)

            elif op_type == "insert":
                line_num = op.get("line")
                new_text = op.get("new_text", "")
                if line_num is None:
                    return f"Error en operacion {i+1}: insert requiere 'line'"
                idx = line_num - 1
                if idx < 0 or idx > len(lines):
                    return f"Error en operacion {i+1}: linea {line_num} fuera de rango (archivo tiene {len(lines)} lineas)"
                new_lines = new_text.splitlines(keepends=True)
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines[-1] += '\n'
                lines[idx:idx] = new_lines
                content = ''.join(lines)
                applied.append(f"insert: {len(new_lines)} linea(s) en posicion {line_num}")

            elif op_type == "delete":
                line_num = op.get("line")
                count = op.get("count", 1)
                if line_num is None:
                    return f"Error en operacion {i+1}: delete requiere 'line'"
                if count < 1:
                    return f"Error en operacion {i+1}: count debe ser >= 1"
                idx = line_num - 1
                if idx < 0 or idx >= len(lines):
                    return f"Error en operacion {i+1}: linea {line_num} fuera de rango (archivo tiene {len(lines)} lineas)"
                end_idx = min(idx + count, len(lines))
                deleted_count = end_idx - idx
                del lines[idx:end_idx]
                content = ''.join(lines)
                applied.append(f"delete: {deleted_count} linea(s) desde posicion {line_num}")

            else:
                return f"Error en operacion {i+1}: operacion desconocida '{op_type}'"

        # Escritura atomica: escribir a archivo temporal, luego renombrar
        temp_path = full_path.with_suffix(full_path.suffix + '.tmp')
        try:
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(content)
            temp_path.replace(full_path)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            return f"Error escribiendo archivo: {e}"

        # Resultado
        final_size = len(content.encode('utf-8'))
        ops_summary = "; ".join(applied)

        if final_size <= MAX_DISPLAY_SIZE:
            return f"Archivo editado ({final_size} bytes, {len(lines)} lineas). Operaciones: {ops_summary}\n```\n{content}\n```"
        else:
            return f"Archivo editado ({final_size} bytes, {len(lines)} lineas). Operaciones: {ops_summary}. Usa read_file para ver el contenido."
