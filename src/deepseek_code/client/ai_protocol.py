"""Protocolo de comunicacion ligero AI-a-AI.

Canal de comunicacion eficiente entre Claude Code y DeepSeek
para operaciones meta (negociacion de skills, briefing, review)
sin activar el sistema de prompts pesado.

Los prompts aqui son ultra-compactos: ~100-200 tokens.
No incluyen reglas de codigo, patrones, ni instrucciones de formato.
Solo la informacion minima para que DeepSeek entienda la operacion.
"""

from typing import List, Optional
from enum import Enum


class AIOperation(Enum):
    """Tipos de operacion AI-a-AI."""
    SKILL_NEGOTIATE = "skill_negotiate"
    BRIEFING = "briefing"
    REVIEW = "review"
    STRATEGY = "strategy"


# --- System prompts ultra-compactos por operacion ---

NEGOTIATE_SYSTEM = (
    "You are a code expert choosing knowledge resources. "
    "Given a task and a catalog of available skills, respond ONLY with "
    "the skill names you need (one per line). "
    "If you don't need any, respond with: NONE. "
    "Choose only what's truly useful — you already know most programming concepts."
)

BRIEFING_SYSTEM = (
    "You are reviewing a project brief before coding. "
    "Read the project info and confirm understanding. "
    "Respond with a very short confirmation (1-3 sentences) "
    "and note any potential issues you foresee."
)

REVIEW_SYSTEM = (
    "You are reviewing code for issues. "
    "Given code and a list of problems, fix ALL issues and return "
    "the COMPLETE corrected code. Do not explain, just code."
)

STRATEGY_SYSTEM = (
    "You are a task analysis expert. "
    "Given a task description, recommend the optimal execution mode: "
    "delegate (single shot), quantum (dual parallel), "
    "multi-session (N instances with roles), or converse (iterative). "
    "Respond with: MODE: <mode>\\nREASON: <one sentence>"
)


def build_negotiate_prompt(task: str, catalog: str) -> str:
    """Construye el prompt para negociacion de skills.

    Args:
        task: Descripcion de la tarea
        catalog: Texto del catalogo de skills

    Returns:
        Prompt listo para enviar (~100 tokens + catalogo)
    """
    return (
        f"TASK: {task[:5000]}\n\n"
        f"{catalog}\n\n"
        "List ONLY the skill names you need (one per line), or NONE:"
    )


def build_briefing_prompt(
    project_info: str,
    task: str,
    conventions: str = "",
) -> str:
    """Construye el prompt de briefing de proyecto.

    Args:
        project_info: Info del proyecto (estructura, archivos clave)
        task: Tarea a realizar
        conventions: Convenciones de codigo (opcional)

    Returns:
        Prompt de briefing compacto
    """
    parts = [f"PROJECT BRIEF:\n{project_info[:20000]}"]
    if conventions:
        parts.append(f"\nCONVENTIONS:\n{conventions[:5000]}")
    parts.append(f"\nTASK: {task[:5000]}")
    parts.append("\nConfirm understanding and note any concerns:")
    return "\n".join(parts)


def build_review_prompt(
    code: str,
    issues: List[str],
) -> str:
    """Construye el prompt de review con issues.

    Args:
        code: Codigo a revisar (truncado si necesario)
        issues: Lista de problemas encontrados

    Returns:
        Prompt de review compacto
    """
    issues_text = "\n".join(f"- {issue}" for issue in issues[:10])
    return (
        f"CODE WITH ISSUES:\n```\n{code[:80000]}\n```\n\n"
        f"PROBLEMS FOUND:\n{issues_text}\n\n"
        "Fix ALL issues. Return COMPLETE corrected code:"
    )


def build_strategy_prompt(
    task: str,
    template_info: str = "",
    project_info: str = "",
) -> str:
    """Construye el prompt para recomendacion de estrategia.

    Args:
        task: Descripcion de la tarea
        template_info: Info del template (si hay)
        project_info: Info del proyecto (si hay)

    Returns:
        Prompt de estrategia compacto
    """
    parts = [f"TASK: {task[:5000]}"]
    if template_info:
        parts.append(f"TEMPLATE: {template_info[:5000]}")
    if project_info:
        parts.append(f"PROJECT: {project_info[:5000]}")
    parts.append(
        "\nModes available: "
        "delegate (single, fast), "
        "quantum (dual parallel, complex), "
        "multi-session (N instances, very complex), "
        "converse (iterative dialogue, refinement). "
        "\nRecommend:"
    )
    return "\n".join(parts)


def get_system_prompt(operation: AIOperation) -> str:
    """Retorna el system prompt para una operacion AI-a-AI.

    Args:
        operation: Tipo de operacion

    Returns:
        System prompt ultra-compacto
    """
    prompts = {
        AIOperation.SKILL_NEGOTIATE: NEGOTIATE_SYSTEM,
        AIOperation.BRIEFING: BRIEFING_SYSTEM,
        AIOperation.REVIEW: REVIEW_SYSTEM,
        AIOperation.STRATEGY: STRATEGY_SYSTEM,
    }
    return prompts.get(operation, "")


def parse_skill_response(response: str) -> List[str]:
    """Parsea la respuesta de DeepSeek a la negociacion de skills.

    DeepSeek responde con nombres de skills (uno por linea).
    Maneja formatos variados: con/sin guiones, numerados, etc.

    Args:
        response: Respuesta cruda de DeepSeek

    Returns:
        Lista de nombres de skills validos
    """
    if not response or "NONE" in response.upper():
        return []

    names = []
    for line in response.strip().split("\n"):
        # Limpiar formato variado
        line = line.strip()
        if not line:
            continue
        # Remover numeracion: "1. ", "- ", "* "
        line = line.lstrip("0123456789.-*) ").strip()
        # Remover backticks
        line = line.strip("`").strip()
        # Validar: debe parecer un nombre de skill (lowercase, guiones)
        if line and len(line) < 60 and not " " in line or "-" in line:
            # Normalizar a formato esperado
            clean = line.lower().replace(" ", "-")
            if len(clean) >= 3:
                names.append(clean)

    return names


def parse_strategy_response(response: str) -> tuple:
    """Parsea la respuesta de recomendacion de estrategia.

    Args:
        response: Respuesta cruda de DeepSeek

    Returns:
        Tupla (modo_recomendado, razon)
    """
    mode = "delegate"  # default
    reason = ""

    for line in response.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("MODE:"):
            mode = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    # Validar modo
    valid_modes = {"delegate", "quantum", "multi-session", "converse"}
    if mode not in valid_modes:
        mode = "delegate"

    return mode, reason
