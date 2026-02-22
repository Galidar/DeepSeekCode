"""Shadow Learning — Aprende de las correcciones manuales del usuario.

Despues de cada delegacion, compara lo que DeepSeek genero con lo que
el usuario realmente commiteo (via git diff). Detecta patrones de
correccion recurrentes y los almacena para inyectar en futuras delegaciones.

Requiere:
- Repositorio git inicializado en el proyecto
- Al menos 1 commit despues de la delegacion
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CorrectionPattern:
    """Patron de correccion aprendido del usuario."""
    pattern_type: str         # "added_error_handling", "renamed_variable", etc.
    description: str          # Descripcion legible
    before: str               # Lo que DeepSeek genero (simplificado)
    after: str                # Lo que el usuario cambio a
    frequency: int = 1
    auto_apply: bool = False

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "description": self.description,
            "example_before": self.before[:200],
            "example_after": self.after[:200],
            "frequency": self.frequency,
            "auto_apply": self.auto_apply,
        }


# Patrones de correccion que buscamos en diffs
CORRECTION_CLASSIFIERS = [
    {
        "type": "added_error_handling",
        "added_patterns": [r"try\s*\{", r"catch\s*\(", r"\.catch\(", r"try:", r"except\s"],
        "description": "Usuario siempre agrega manejo de errores (try/catch)",
    },
    {
        "type": "added_logging",
        "added_patterns": [r"console\.log\(", r"console\.error\(", r"print\(", r"logger\."],
        "description": "Usuario siempre agrega logging/debug prints",
    },
    {
        "type": "added_null_check",
        "added_patterns": [r"if\s*\(.+\s*!=\s*null", r"if\s*\(.+\?\.", r"\?\?", r"is not None"],
        "description": "Usuario siempre agrega verificaciones de null/undefined",
    },
    {
        "type": "added_type_annotation",
        "added_patterns": [r":\s*(string|number|boolean|int|str|float|dict|list)\b"],
        "description": "Usuario siempre agrega anotaciones de tipo",
    },
    {
        "type": "style_let_to_const",
        "added_patterns": [r"\bconst\s+\w+\s*="],
        "removed_patterns": [r"\blet\s+\w+\s*="],
        "description": "Usuario cambia let a const",
    },
    {
        "type": "style_const_to_let",
        "added_patterns": [r"\blet\s+\w+\s*="],
        "removed_patterns": [r"\bconst\s+\w+\s*="],
        "description": "Usuario cambia const a let",
    },
    {
        "type": "added_comments",
        "added_patterns": [r"^\s*//", r"^\s*#", r"^\s*/\*\*"],
        "description": "Usuario siempre agrega comentarios al codigo",
    },
]


def learn_from_user_corrections(
    project_root: str,
    last_delegation_response: str = "",
    max_commits_to_check: int = 3,
) -> List[CorrectionPattern]:
    """Compara la salida de DeepSeek con los cambios reales del usuario.

    Ejecuta git diff HEAD~N..HEAD para obtener lo que el usuario cambio
    despues de la delegacion, y extrae patrones de correccion.

    Args:
        project_root: Ruta raiz del proyecto (con .git)
        last_delegation_response: Respuesta de DeepSeek (para comparacion)
        max_commits_to_check: Cuantos commits recientes revisar

    Returns:
        Lista de CorrectionPattern aprendidos
    """
    if not _has_git(project_root):
        return []

    # Obtener diff de los ultimos N commits
    diff_text = _get_recent_diff(project_root, max_commits_to_check)
    if not diff_text:
        return []

    # Analizar diff y extraer correcciones
    corrections = detect_corrections_from_diff(diff_text, last_delegation_response)

    return corrections


def detect_corrections_from_diff(
    diff_text: str,
    delegation_response: str = "",
) -> List[CorrectionPattern]:
    """Analiza un git diff y extrae patrones de correccion."""
    added_lines, removed_lines = _parse_diff_lines(diff_text)
    corrections = []

    # Buscar patrones clasificados
    for classifier in CORRECTION_CLASSIFIERS:
        added_match = False
        removed_match = False

        # Verificar lineas agregadas
        for pattern in classifier.get("added_patterns", []):
            for line in added_lines:
                if re.search(pattern, line):
                    added_match = True
                    break
            if added_match:
                break

        # Verificar lineas removidas (si el clasificador lo requiere)
        removed_patterns = classifier.get("removed_patterns", [])
        if removed_patterns:
            for pattern in removed_patterns:
                for line in removed_lines:
                    if re.search(pattern, line):
                        removed_match = True
                        break
                if removed_match:
                    break
            # Este tipo requiere ambas: lineas agregadas Y removidas
            if not (added_match and removed_match):
                continue
        elif not added_match:
            continue

        # Encontrar ejemplo concreto
        before_ex = _find_example(removed_lines, classifier.get("removed_patterns", []))
        after_ex = _find_example(added_lines, classifier["added_patterns"])

        corrections.append(CorrectionPattern(
            pattern_type=classifier["type"],
            description=classifier["description"],
            before=before_ex,
            after=after_ex,
        ))

    # Detectar renombramientos sistematicos
    renames = _extract_naming_patterns(added_lines, removed_lines)
    corrections.extend(renames)

    return corrections


def _has_git(project_root: str) -> bool:
    """Verifica si el directorio tiene .git."""
    return os.path.isdir(os.path.join(project_root, ".git"))


def _get_recent_diff(project_root: str, max_commits: int) -> str:
    """Obtiene git diff de los ultimos N commits."""
    try:
        result = subprocess.run(
            ["git", "diff", f"HEAD~{max_commits}..HEAD", "--unified=0"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        # Si no hay suficientes commits, intentar con menos
        if max_commits > 1:
            return _get_recent_diff(project_root, max_commits - 1)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def _parse_diff_lines(diff_text: str) -> tuple:
    """Parsea un diff unificado y separa lineas agregadas y removidas."""
    added = []
    removed = []
    for line in diff_text.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())
    return added, removed


def _find_example(lines: list, patterns: list) -> str:
    """Busca un ejemplo concreto que haga match con los patrones."""
    for pattern in patterns:
        for line in lines:
            if re.search(pattern, line):
                return line[:200]
    return ""


def _extract_naming_patterns(
    added_lines: list,
    removed_lines: list,
) -> List[CorrectionPattern]:
    """Detecta renombramientos sistematicos (ej: data->result, cb->callback)."""
    renames = []

    # Extraer nombres de variables/funciones
    added_names = set()
    removed_names = set()
    name_pattern = r"\b([a-zA-Z_]\w{2,30})\b"

    for line in added_lines[:100]:
        added_names.update(re.findall(name_pattern, line))
    for line in removed_lines[:100]:
        removed_names.update(re.findall(name_pattern, line))

    # Nombres que aparecen en added pero no en removed (y viceversa)
    new_names = added_names - removed_names
    old_names = removed_names - added_names

    # Buscar pares de renombramiento por similitud
    for old in list(old_names)[:10]:
        for new in list(new_names)[:10]:
            # Heuristica: un nombre contiene al otro o comparten prefijo
            if (old in new or new in old) and old != new:
                renames.append(CorrectionPattern(
                    pattern_type="renamed_variable",
                    description=f"Usuario renombra '{old}' a '{new}'",
                    before=old,
                    after=new,
                ))
                break

    return renames[:5]


def build_shadow_briefing(store_data: dict, token_budget: int = 500) -> str:
    """Construye briefing con correcciones aprendidas para inyectar.

    Args:
        store_data: Dict crudo del SurgicalStore
        token_budget: Presupuesto de tokens para el briefing

    Returns:
        String formateado para inyectar en system prompt
    """
    corrections = store_data.get("shadow_corrections", [])
    if not corrections:
        return ""

    # Solo correcciones significativas (frecuencia >= 2)
    significant = [c for c in corrections if c.get("frequency", 0) >= 2]
    if not significant:
        return ""

    significant.sort(key=lambda x: x.get("frequency", 0), reverse=True)

    lines = [
        "PATRONES APRENDIDOS DEL USUARIO (aplicar automaticamente):",
    ]

    for c in significant[:7]:
        freq = c.get("frequency", 0)
        desc = c.get("description", "")
        lines.append(f"  [{freq}x] {desc}")
        before = c.get("example_before", "")
        after = c.get("example_after", "")
        if before and after:
            lines.append(f"         Antes: {before[:80]}")
            lines.append(f"         Ahora: {after[:80]}")

    result = "\n".join(lines) + "\n"

    # Truncar si excede budget
    estimated = len(result) // 4
    if estimated > token_budget:
        max_chars = token_budget * 4
        result = result[:max_chars] + "\n[... truncado ...]\n"

    return result
