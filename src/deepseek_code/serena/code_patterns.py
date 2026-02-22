"""Patrones regex para deteccion de simbolos de codigo por lenguaje.

Usado por native_tools.py para detectar clases, funciones, variables, etc.
en archivos de distintos lenguajes de programacion.
"""

import os
import re
from pathlib import Path
from typing import List, Optional

# Directorios y archivos a ignorar en busquedas
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".cache", ".tox", "egg-info",
    ".mypy_cache", ".pytest_cache", "coverage",
}
IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".mp3", ".mp4", ".wav", ".avi",
    ".pdf", ".doc", ".docx", ".xls",
    ".wasm", ".bin", ".dat",
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB max por archivo

# Patrones regex por lenguaje para detectar simbolos
SYMBOL_PATTERNS = {
    ".py": {
        "class": r"^class\s+(\w+)",
        "function": r"^(?:async\s+)?def\s+(\w+)",
        "variable": r"^(\w+)\s*(?::\s*\w+)?\s*=",
    },
    ".js": {
        "class": r"^(?:export\s+)?class\s+(\w+)",
        "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        "arrow": r"^(?:export\s+)?(?:let|const|var)\s+(\w+)\s*=\s*(?:async\s+)?\(",
        "variable": r"^(?:export\s+)?(?:let|const|var)\s+(\w+)\s*=",
    },
    ".ts": {
        "class": r"^(?:export\s+)?class\s+(\w+)",
        "interface": r"^(?:export\s+)?interface\s+(\w+)",
        "type": r"^(?:export\s+)?type\s+(\w+)",
        "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        "arrow": r"^(?:export\s+)?(?:let|const|var)\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:async\s+)?\(",
        "variable": r"^(?:export\s+)?(?:let|const|var)\s+(\w+)\s*(?::\s*[^=]+)?\s*=",
    },
    ".java": {
        "class": r"^(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)",
        "interface": r"^(?:public|private|protected)?\s*interface\s+(\w+)",
        "method": r"^\s+(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?\w+\s+(\w+)\s*\(",
    },
    ".go": {
        "function": r"^func\s+(\w+)",
        "method": r"^func\s+\([^)]+\)\s+(\w+)",
        "type": r"^type\s+(\w+)",
    },
    ".rust": {
        "function": r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
        "struct": r"^(?:pub\s+)?struct\s+(\w+)",
        "enum": r"^(?:pub\s+)?enum\s+(\w+)",
        "trait": r"^(?:pub\s+)?trait\s+(\w+)",
        "impl": r"^impl(?:<[^>]+>)?\s+(\w+)",
    },
}
# Extensiones que comparten patrones
SYMBOL_PATTERNS[".jsx"] = SYMBOL_PATTERNS[".js"]
SYMBOL_PATTERNS[".tsx"] = SYMBOL_PATTERNS[".ts"]
SYMBOL_PATTERNS[".mjs"] = SYMBOL_PATTERNS[".js"]
SYMBOL_PATTERNS[".rs"] = SYMBOL_PATTERNS[".rust"]


def should_skip(path: Path) -> bool:
    """Verifica si un archivo/directorio debe ignorarse."""
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False


def is_text_file(path: Path) -> bool:
    """Verifica si un archivo es de texto y no esta en la lista de ignorados."""
    if path.suffix.lower() in IGNORE_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def iter_project_files(
    base_path: str,
    file_glob: str = "",
    allowed_paths: Optional[List[str]] = None,
) -> List[Path]:
    """Itera archivos de texto en el proyecto respetando filtros."""
    base = Path(base_path)
    if not base.exists():
        return []

    results = []
    if base.is_file():
        if is_text_file(base):
            results.append(base)
        return results

    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for fname in files:
            fpath = root_path / fname
            if should_skip(fpath):
                continue
            if not is_text_file(fpath):
                continue
            if file_glob:
                if not fpath.match(file_glob):
                    continue
            results.append(fpath)

    return results


def read_file_lines(path: Path) -> List[str]:
    """Lee un archivo como lista de lineas, manejando encodings."""
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.readlines()
        except (UnicodeDecodeError, OSError):
            continue
    return []


def extract_python_body(lines: List[str], start: int) -> str:
    """Extrae cuerpo Python por indentacion."""
    if start >= len(lines):
        return ""

    first_line = lines[start]
    base_indent = len(first_line) - len(first_line.lstrip())
    body_lines = [first_line.rstrip()]

    for i in range(start + 1, min(start + 200, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            body_lines.append("")
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= base_indent and stripped:
            break
        body_lines.append(line.rstrip())

    if len(body_lines) > 80:
        body_lines = body_lines[:80]
        body_lines.append("    # ... (truncado)")

    return "\n".join(body_lines)


def extract_brace_body(lines: List[str], start: int) -> str:
    """Extrae cuerpo por llaves (JS, TS, Java, Go, Rust)."""
    body_lines = []
    brace_count = 0
    found_open = False

    for i in range(start, min(start + 200, len(lines))):
        line = lines[i]
        body_lines.append(line.rstrip())

        for ch in line:
            if ch == "{":
                brace_count += 1
                found_open = True
            elif ch == "}":
                brace_count -= 1

        if found_open and brace_count <= 0:
            break

    if len(body_lines) > 80:
        body_lines = body_lines[:80]
        body_lines.append("  // ... (truncado)")

    return "\n".join(body_lines)
