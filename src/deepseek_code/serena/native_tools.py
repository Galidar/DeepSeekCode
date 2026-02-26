"""Herramientas nativas de analisis de codigo para DeepSeek-Code.

Reemplaza las herramientas de Serena (search_for_pattern, get_symbols_overview,
find_symbol) usando regex puro, sin necesidad de instalar serena-agent.
Funcionan con cualquier proyecto local.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..server.tool import BaseTool
from .code_patterns import (
    SYMBOL_PATTERNS, iter_project_files, read_file_lines,
    extract_python_body, extract_brace_body,
)


class SearchPatternTool(BaseTool):
    """Busca un patron regex en archivos del proyecto."""

    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self.allowed_paths = allowed_paths or []
        super().__init__(
            name="serena_search_for_pattern",
            description=(
                "Busca un patron regex en archivos del proyecto. "
                "Retorna coincidencias con contexto de lineas alrededor."
            )
        )

    def _build_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "substring_pattern": {
                    "type": "string",
                    "description": "Patron regex a buscar"
                },
                "relative_path": {
                    "type": "string",
                    "description": "Ruta relativa al directorio o archivo donde buscar",
                    "default": ""
                },
                "file_glob": {
                    "type": "string",
                    "description": "Filtro glob para archivos (ej: '*.py', '*.ts')",
                    "default": ""
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lineas de contexto antes y despues (default: 2)",
                    "default": 2
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximo de resultados (default: 30)",
                    "default": 30
                },
            },
            "required": ["substring_pattern"]
        }

    async def execute(self, **kwargs) -> Any:
        pattern_str = kwargs.get("substring_pattern", "")
        relative_path = kwargs.get("relative_path", "")
        file_glob = kwargs.get("file_glob", "")
        context_lines = kwargs.get("context_lines", 2)
        max_results = min(kwargs.get("max_results", 30), 100)

        if not pattern_str:
            return {"error": "Se requiere substring_pattern"}

        try:
            regex = re.compile(pattern_str, re.MULTILINE | re.DOTALL)
        except re.error as e:
            return {"error": f"Regex invalido: {e}"}

        search_path = self.allowed_paths[0] if self.allowed_paths else "."
        if relative_path:
            search_path = os.path.join(search_path, relative_path)

        files = iter_project_files(search_path, file_glob, self.allowed_paths)
        results = {}
        total_matches = 0

        for fpath in files:
            if total_matches >= max_results:
                break

            lines = read_file_lines(fpath)
            if not lines:
                continue

            full_text = "".join(lines)
            for match in regex.finditer(full_text):
                if total_matches >= max_results:
                    break

                line_num = full_text[:match.start()].count("\n")
                start_line = max(0, line_num - context_lines)
                end_line = min(len(lines), line_num + context_lines + 1)

                snippet = []
                for i in range(start_line, end_line):
                    prefix = ">> " if i == line_num else "   "
                    snippet.append(f"{prefix}{i + 1}: {lines[i].rstrip()}")

                rel = str(fpath)
                try:
                    base = self.allowed_paths[0] if self.allowed_paths else "."
                    rel = str(fpath.relative_to(base))
                except ValueError:
                    pass

                if rel not in results:
                    results[rel] = []
                results[rel].append({
                    "line": line_num + 1,
                    "snippet": "\n".join(snippet)
                })
                total_matches += 1

        return {
            "matches": results,
            "total_matches": total_matches,
            "files_searched": len(files),
        }


class SymbolsOverviewTool(BaseTool):
    """Lista simbolos (clases, funciones, variables) de un archivo."""

    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self.allowed_paths = allowed_paths or []
        super().__init__(
            name="serena_get_symbols_overview",
            description=(
                "Lista clases, funciones y variables de un archivo. "
                "Soporta Python, JavaScript, TypeScript, Java, Go, Rust."
            )
        )

    def _build_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Ruta relativa al archivo a analizar"
                },
            },
            "required": ["relative_path"]
        }

    async def execute(self, **kwargs) -> Any:
        relative_path = kwargs.get("relative_path", "")
        if not relative_path:
            return {"error": "Se requiere relative_path"}

        base = self.allowed_paths[0] if self.allowed_paths else "."
        full_path = Path(base) / relative_path

        if not full_path.exists():
            return {"error": f"Archivo no encontrado: {relative_path}"}
        if not full_path.is_file():
            return {"error": f"No es un archivo: {relative_path}"}

        ext = full_path.suffix.lower()
        patterns = SYMBOL_PATTERNS.get(ext)
        if not patterns:
            return {
                "error": f"Extension no soportada: {ext}",
                "supported": list(SYMBOL_PATTERNS.keys())
            }

        lines = read_file_lines(full_path)
        if not lines:
            return {"error": "No se pudo leer el archivo"}

        symbols = {}
        for kind, pattern in patterns.items():
            compiled = re.compile(pattern, re.MULTILINE)
            found = []
            for i, line in enumerate(lines):
                m = compiled.match(line)
                if m:
                    found.append({
                        "name": m.group(1),
                        "line": i + 1,
                        "preview": line.strip()[:500],
                    })
            if found:
                symbols[kind] = found

        return {
            "file": relative_path,
            "extension": ext,
            "total_lines": len(lines),
            "symbols": symbols,
        }


class FindSymbolTool(BaseTool):
    """Busca definiciones de un simbolo por nombre en el proyecto."""

    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self.allowed_paths = allowed_paths or []
        super().__init__(
            name="serena_find_symbol",
            description=(
                "Busca definiciones de clases, funciones o variables por nombre "
                "en todo el proyecto. Retorna ubicacion y contexto."
            )
        )

    def _build_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name_path_pattern": {
                    "type": "string",
                    "description": "Nombre del simbolo a buscar"
                },
                "relative_path": {
                    "type": "string",
                    "description": "Restringir busqueda a esta ruta",
                    "default": ""
                },
                "include_body": {
                    "type": "boolean",
                    "description": "Incluir el cuerpo completo del simbolo",
                    "default": False
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximo de resultados (default: 20)",
                    "default": 20
                },
            },
            "required": ["name_path_pattern"]
        }

    async def execute(self, **kwargs) -> Any:
        name_pattern = kwargs.get("name_path_pattern", "")
        relative_path = kwargs.get("relative_path", "")
        include_body = kwargs.get("include_body", False)
        max_results = min(kwargs.get("max_results", 20), 50)

        if not name_pattern:
            return {"error": "Se requiere name_path_pattern"}

        parts = name_pattern.strip("/").split("/")
        symbol_name = parts[-1]

        base = self.allowed_paths[0] if self.allowed_paths else "."
        search_path = os.path.join(base, relative_path) if relative_path else base

        files = iter_project_files(search_path, "", self.allowed_paths)
        results = []

        for fpath in files:
            if len(results) >= max_results:
                break

            ext = fpath.suffix.lower()
            patterns = SYMBOL_PATTERNS.get(ext)
            if not patterns:
                continue

            lines = read_file_lines(fpath)
            if not lines:
                continue

            for kind, pattern in patterns.items():
                compiled = re.compile(pattern, re.MULTILINE)
                for i, line in enumerate(lines):
                    m = compiled.match(line)
                    if m and m.group(1) == symbol_name:
                        rel = str(fpath)
                        try:
                            rel = str(fpath.relative_to(base))
                        except ValueError:
                            pass

                        entry = {
                            "name": symbol_name,
                            "kind": kind,
                            "file": rel,
                            "line": i + 1,
                            "preview": line.strip()[:500],
                        }

                        if include_body:
                            if ext == ".py":
                                entry["body"] = extract_python_body(lines, i)
                            else:
                                entry["body"] = extract_brace_body(lines, i)

                        results.append(entry)
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break

        return {
            "symbol": name_pattern,
            "results": results,
            "total_found": len(results),
        }
