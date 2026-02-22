"""Git Intelligence — Deteccion y resolucion AI de conflictos de merge.

Detecta archivos con conflictos de merge en un repositorio git,
parsea los marcadores de conflicto, y genera resoluciones inteligentes
usando DeepSeek con contexto del proyecto.

Requiere: repositorio git con conflictos activos.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ConflictInfo:
    """Informacion sobre un conflicto de merge en un archivo."""
    file_path: str
    ours: str                 # Contenido del lado "nuestro" (HEAD)
    theirs: str               # Contenido del lado "entrante"
    context_before: str       # Lineas antes del conflicto
    context_after: str        # Lineas despues del conflicto
    conflict_index: int = 0   # Indice del conflicto en el archivo


@dataclass
class ConflictResolution:
    """Resolucion propuesta para un conflicto."""
    file_path: str
    resolved_content: str     # Contenido completo del archivo resuelto
    strategy: str             # "ours", "theirs", "merge", "ai_resolved"
    explanation: str          # Explicacion de la decision
    conflicts_resolved: int   # Cuantos conflictos se resolvieron

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "strategy": self.strategy,
            "explanation": self.explanation,
            "conflicts_resolved": self.conflicts_resolved,
            "preview": self.resolved_content[:500] + "..." if len(self.resolved_content) > 500 else self.resolved_content,
        }


# Regex para marcadores de conflicto git
CONFLICT_START = re.compile(r"^<<<<<<<\s*(.*)", re.MULTILINE)
CONFLICT_SEPARATOR = re.compile(r"^=======\s*$", re.MULTILINE)
CONFLICT_END = re.compile(r"^>>>>>>>\s*(.*)", re.MULTILINE)


def detect_conflicts(project_root: str) -> List[str]:
    """Detecta archivos con conflictos de merge via git status.

    Returns:
        Lista de rutas relativas de archivos con conflictos
    """
    if not os.path.isdir(os.path.join(project_root, ".git")):
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return []


def parse_conflict_markers(file_content: str) -> List[ConflictInfo]:
    """Parsea marcadores de conflicto de un archivo.

    Extrae cada bloque <<<<<<< ... ======= ... >>>>>>> con contexto.

    Returns:
        Lista de ConflictInfo con ours/theirs/context
    """
    conflicts = []
    lines = file_content.split("\n")
    i = 0
    conflict_idx = 0

    while i < len(lines):
        line = lines[i]

        # Detectar inicio de conflicto
        if line.startswith("<<<<<<<"):
            # Contexto antes (3 lineas)
            ctx_start = max(0, i - 3)
            context_before = "\n".join(lines[ctx_start:i])

            # Buscar separator (=======)
            ours_lines = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith("======="):
                ours_lines.append(lines[j])
                j += 1

            # Buscar fin (>>>>>>>)
            theirs_lines = []
            k = j + 1
            while k < len(lines) and not lines[k].startswith(">>>>>>>"):
                theirs_lines.append(lines[k])
                k += 1

            # Contexto despues (3 lineas)
            ctx_end = min(len(lines), k + 4)
            context_after = "\n".join(lines[k + 1:ctx_end])

            conflicts.append(ConflictInfo(
                file_path="",  # Se establece externamente
                ours="\n".join(ours_lines),
                theirs="\n".join(theirs_lines),
                context_before=context_before,
                context_after=context_after,
                conflict_index=conflict_idx,
            ))
            conflict_idx += 1
            i = k + 1
        else:
            i += 1

    return conflicts


def get_all_conflicts(project_root: str) -> List[ConflictInfo]:
    """Obtiene todos los conflictos de todos los archivos afectados.

    Returns:
        Lista de ConflictInfo con file_path establecido
    """
    conflict_files = detect_conflicts(project_root)
    all_conflicts = []

    for rel_path in conflict_files:
        full_path = os.path.join(project_root, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (IOError, OSError):
            continue

        file_conflicts = parse_conflict_markers(content)
        for conflict in file_conflicts:
            conflict.file_path = rel_path
        all_conflicts.extend(file_conflicts)

    return all_conflicts


def build_resolution_prompt(conflict: ConflictInfo, project_context: str = "") -> str:
    """Construye prompt para que DeepSeek resuelva un conflicto.

    Returns:
        Prompt optimizado para resolucion inteligente
    """
    parts = [
        "Resuelve el siguiente conflicto de merge de forma inteligente.",
        f"Archivo: {conflict.file_path}",
        "",
        "Contexto ANTES del conflicto:",
        conflict.context_before or "(inicio del archivo)",
        "",
        "LADO NUESTRO (HEAD / branch actual):",
        conflict.ours,
        "",
        "LADO ENTRANTE (merge branch):",
        conflict.theirs,
        "",
        "Contexto DESPUES del conflicto:",
        conflict.context_after or "(fin del archivo)",
    ]

    if project_context:
        parts.extend([
            "",
            "Contexto del proyecto:",
            project_context[:500],
        ])

    parts.extend([
        "",
        "Instrucciones:",
        "1. Analiza ambos lados y decide la mejor integracion",
        "2. Si ambos lados agregan funcionalidad diferente, combina ambos",
        "3. Si son cambios conflictivos al mismo codigo, elige el mas completo",
        "4. Retorna SOLO el codigo resuelto (sin marcadores de conflicto)",
    ])

    return "\n".join(parts)


def resolve_conflict_simple(conflict: ConflictInfo) -> ConflictResolution:
    """Resolucion simple sin AI — elige el lado mas largo/completo.

    Util como fallback cuando no hay cliente DeepSeek disponible.
    """
    ours_len = len(conflict.ours.strip())
    theirs_len = len(conflict.theirs.strip())

    if ours_len >= theirs_len:
        return ConflictResolution(
            file_path=conflict.file_path,
            resolved_content=conflict.ours,
            strategy="ours",
            explanation="Lado nuestro mas largo/completo (resolucion heuristica)",
            conflicts_resolved=1,
        )
    return ConflictResolution(
        file_path=conflict.file_path,
        resolved_content=conflict.theirs,
        strategy="theirs",
        explanation="Lado entrante mas largo/completo (resolucion heuristica)",
        conflicts_resolved=1,
    )


def apply_resolution(file_path: str, original_content: str, resolutions: list) -> str:
    """Aplica resoluciones a un archivo reemplazando marcadores de conflicto.

    Args:
        file_path: Ruta al archivo (para logging)
        original_content: Contenido original con marcadores
        resolutions: Lista de strings con codigo resuelto (uno por conflicto)

    Returns:
        Contenido del archivo con conflictos resueltos
    """
    result_lines = []
    lines = original_content.split("\n")
    resolution_idx = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("<<<<<<<") and resolution_idx < len(resolutions):
            # Insertar resolucion
            result_lines.append(resolutions[resolution_idx])

            # Saltar hasta despues de >>>>>>>
            while i < len(lines) and not lines[i].startswith(">>>>>>>"):
                i += 1
            resolution_idx += 1
            i += 1  # Saltar la linea >>>>>>>
        else:
            result_lines.append(line)
            i += 1

    return "\n".join(result_lines)
