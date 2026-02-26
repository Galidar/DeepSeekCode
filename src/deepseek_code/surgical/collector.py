"""Captura automatica de contexto para SurgicalMemory.

Detecta el proyecto activo, extrae informacion de CLAUDE.md,
y registra resultados de delegaciones para aprendizaje.
"""

import os
import re
from typing import Optional, List


# Archivos que indican la raiz de un proyecto
PROJECT_MARKERS = [
    "CLAUDE.md", "package.json", "pyproject.toml",
    "Cargo.toml", "go.mod", ".git",
]

# Secciones de CLAUDE.md relevantes para delegacion
CLAUDE_MD_KEYWORDS = [
    "estructura", "structure", "reglas", "rules",
    "patron", "pattern", "convencion", "convention",
    "architecture", "arquitectura", "instrucciones",
    "instructions", "critica", "critical", "importante",
]

MAX_CLAUDE_MD_CHARS = 6000  # ~1700 tokens


def detect_project_root(file_path: str) -> Optional[str]:
    """Detecta la raiz del proyecto subiendo por el arbol de directorios.

    Busca archivos marcadores como CLAUDE.md, package.json, .git, etc.

    Args:
        file_path: Ruta a un archivo del proyecto (template, context, etc.)

    Returns:
        Ruta a la raiz del proyecto, o None si no se detecta
    """
    if not file_path or not os.path.exists(file_path):
        return None

    current = os.path.dirname(os.path.abspath(file_path))
    for _ in range(10):  # Max 10 niveles arriba
        for marker in PROJECT_MARKERS:
            if os.path.exists(os.path.join(current, marker)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def extract_claude_md(project_root: str) -> Optional[str]:
    """Extrae informacion relevante del CLAUDE.md del proyecto.

    Filtra solo las secciones utiles para delegacion (arquitectura,
    convenciones, reglas) y trunca a MAX_CLAUDE_MD_CHARS.

    Args:
        project_root: Raiz del proyecto

    Returns:
        Texto extraido o None
    """
    claude_path = os.path.join(project_root, "CLAUDE.md")
    if not os.path.exists(claude_path):
        return None

    try:
        with open(claude_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except IOError:
        return None

    if not content.strip():
        return None

    if len(content) <= MAX_CLAUDE_MD_CHARS:
        return content

    # Extraer solo secciones relevantes
    sections = _extract_relevant_sections(content)
    if sections:
        result = "\n\n".join(sections)
        if len(result) > MAX_CLAUDE_MD_CHARS:
            return result[:MAX_CLAUDE_MD_CHARS] + "\n[... truncado ...]"
        return result

    return content[:MAX_CLAUDE_MD_CHARS] + "\n[... truncado ...]"


def _extract_relevant_sections(content: str) -> List[str]:
    """Extrae secciones relevantes del Markdown por encabezados."""
    sections = []
    current_section = []
    is_relevant = False

    for line in content.splitlines():
        if line.startswith("#"):
            # Guardar seccion anterior si era relevante
            if is_relevant and current_section:
                sections.append("\n".join(current_section))
            current_header = line.lower()
            current_section = [line]
            is_relevant = any(
                kw in current_header for kw in CLAUDE_MD_KEYWORDS
            )
        else:
            current_section.append(line)

    # Guardar ultima seccion
    if is_relevant and current_section:
        sections.append("\n".join(current_section))

    return sections


def build_delegation_record(
    task: str,
    mode: str,
    success: bool,
    duration_s: float,
    validation: dict = None,
    response_stats: dict = None,
) -> dict:
    """Construye un registro de delegacion para el historial.

    Args:
        task: Descripcion de la tarea
        mode: "delegate", "quantum", "multi_step"
        success: Si la delegacion fue exitosa
        duration_s: Duracion en segundos
        validation: Resultado del validador (opcional)
        response_stats: Estadisticas de la respuesta (opcional)

    Returns:
        dict con el registro completo
    """
    record = {
        "task": task[:2000],
        "mode": mode,
        "success": success,
        "duration_s": round(duration_s, 1),
    }

    if validation:
        record["validation"] = {
            "valid": validation.get("valid", False),
            "truncated": validation.get("truncated", False),
            "issues": validation.get("issues", [])[:5],
            "todos_missing": validation.get("todos_missing", [])[:5],
        }

    if response_stats:
        record["response_stats"] = {
            "lines": response_stats.get("lines", 0),
            "chars": response_stats.get("chars", 0),
            "functions": response_stats.get("functions", 0),
        }

    return record


def extract_error_entry(validation: dict, task: str) -> Optional[dict]:
    """Extrae una entrada de error del resultado de validacion.

    Solo se crea si hay errores reales (no si fue exitoso).

    Returns:
        dict con la entrada o None si no hay errores
    """
    if not validation:
        return None
    if validation.get("valid") and not validation.get("truncated"):
        return None

    entry = {"task_summary": task[:1000]}
    issues = validation.get("issues", [])
    if issues:
        entry["issues"] = issues[:5]

    if validation.get("truncated"):
        entry["type"] = "truncation"
    elif validation.get("todos_missing"):
        entry["type"] = "missing_todos"
        entry["missing"] = validation["todos_missing"][:5]
    else:
        entry["type"] = "validation_failure"

    return entry
