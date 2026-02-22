"""Motor de aprendizaje global cross-proyecto para GlobalMemory.

Analiza cada delegacion completada y extrae patrones personales:
estilo de codigo, efectividad de skills, complejidad optima,
rendimiento por modo, errores recurrentes, keywords exitosas.
"""

import re
from typing import Dict, List, Optional

from .global_store import GlobalStore


# Media movil exponencial: alpha controla peso de nuevas muestras
EMA_ALPHA = 0.15

# Palabras ignoradas al extraer keywords
_STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "que",
    "en", "con", "para", "por", "todo", "todos", "cada", "como",
    "the", "a", "an", "of", "to", "and", "or", "for", "in",
    "implementar", "implement", "crear", "create", "hacer", "make",
    "codigo", "code", "funcion", "function", "que", "sea", "debe",
}


def learn_global(
    store: GlobalStore,
    task: str,
    mode: str,
    success: bool,
    response: str,
    validation: Optional[dict] = None,
    duration_s: float = 0.0,
    skills_injected: Optional[List[str]] = None,
    token_usage: Optional[dict] = None,
    project_name: str = "",
):
    """Punto de entrada: analiza una delegacion y actualiza la memoria global.

    Args:
        store: GlobalStore cargado
        task: Descripcion de la tarea
        mode: "delegate", "quantum", "multi_step"
        success: Si la respuesta fue valida
        response: Respuesta de DeepSeek
        validation: Resultado de validate_delegate_response
        duration_s: Duracion en segundos
        skills_injected: Lista de nombres de skills inyectadas
        token_usage: Desglose de tokens consumidos
        project_name: Nombre del proyecto (para errores cross-proyecto)
    """
    store.data["total_delegations"] = store.data.get("total_delegations", 0) + 1
    truncated = validation.get("truncated", False) if validation else False

    _update_code_style(store, response, success)
    _update_skill_stats(store, skills_injected, success, truncated)
    _update_complexity(store, token_usage, validation, success)
    _update_mode_stats(store, mode, success, duration_s)
    _update_cross_errors(store, validation, project_name, success)
    _update_task_keywords(store, task, success)

    store.save()


def _update_code_style(store: GlobalStore, response: str, success: bool):
    """Acumula preferencias de estilo de codigo del usuario."""
    if not success or not response:
        return
    style = store.data.setdefault("code_style", {})

    # let vs const
    let_count = len(re.findall(r'\blet\b', response))
    const_count = len(re.findall(r'\bconst\b', response))
    style["let_count"] = style.get("let_count", 0) + let_count
    style["const_count"] = style.get("const_count", 0) + const_count
    total_vars = style["let_count"] + style["const_count"]
    if total_vars > 0:
        style["let_preference"] = style["let_count"] > style["const_count"]

    # camelCase vs snake_case
    camel = len(re.findall(r'\b[a-z]+[A-Z]\w+\b', response))
    snake = len(re.findall(r'\b[a-z]+_[a-z]+\b', response))
    style["camel_count"] = style.get("camel_count", 0) + camel
    style["snake_count"] = style.get("snake_count", 0) + snake
    total_naming = style["camel_count"] + style["snake_count"]
    if total_naming > 0:
        style["naming_preference"] = (
            "camelCase" if style["camel_count"] > style["snake_count"]
            else "snake_case"
        )

    # Idioma de comentarios
    comment_lines = re.findall(r'//\s*(.+)', response)
    es_words = {"para", "con", "del", "por", "esta", "tiene", "cada", "como"}
    en_words = {"the", "this", "for", "with", "from", "that", "each", "when"}
    for line in comment_lines[:20]:
        words = set(line.lower().split())
        if words & es_words:
            style["comment_es"] = style.get("comment_es", 0) + 1
        if words & en_words:
            style["comment_en"] = style.get("comment_en", 0) + 1
    total_comments = style.get("comment_es", 0) + style.get("comment_en", 0)
    if total_comments > 0:
        style["comment_lang"] = (
            "es" if style.get("comment_es", 0) > style.get("comment_en", 0)
            else "en"
        )


def _update_skill_stats(
    store: GlobalStore, skills: Optional[List[str]],
    success: bool, truncated: bool,
):
    """Actualiza estadisticas por skill inyectada y combinaciones."""
    if not skills:
        return
    for skill in skills:
        store.update_skill_stat(skill, success, truncated)
    # Registrar combinacion (solo domain skills, sin core)
    from deepseek_code.skills.skill_constants import CORE_SKILLS
    domain_skills = [s for s in skills if s not in CORE_SKILLS]
    if len(domain_skills) >= 2:
        store.update_skill_combo(domain_skills, success)


def _update_complexity(
    store: GlobalStore, token_usage: Optional[dict],
    validation: Optional[dict], success: bool,
):
    """Actualiza estadisticas de complejidad optima con EMA."""
    comp = store.data.setdefault("complexity_stats", {})

    if token_usage and success:
        total_input = token_usage.get("total_input", 0)
        if total_input > 0:
            prev_avg = comp.get("avg_input_tokens", 0)
            samples = comp.get("successful_samples", 0)
            if samples == 0:
                comp["avg_input_tokens"] = total_input
            else:
                comp["avg_input_tokens"] = round(
                    prev_avg * (1 - EMA_ALPHA) + total_input * EMA_ALPHA
                )
            comp["sweet_spot_input_tokens"] = comp["avg_input_tokens"]
            comp["successful_samples"] = samples + 1

    if validation and success:
        found = len(validation.get("todos_found", []))
        missing = len(validation.get("todos_missing", []))
        total_todos = found + missing
        if total_todos > 0:
            prev_avg = comp.get("avg_todos", 0)
            samples = comp.get("successful_samples", 0)
            if samples <= 1:
                comp["avg_todos"] = total_todos
            else:
                comp["avg_todos"] = round(
                    prev_avg * (1 - EMA_ALPHA) + total_todos * EMA_ALPHA, 1
                )
            comp["sweet_spot_todos"] = max(1, round(comp["avg_todos"]))


def _update_mode_stats(
    store: GlobalStore, mode: str, success: bool, duration_s: float,
):
    """Actualiza estadisticas de rendimiento por modo."""
    modes = store.data.setdefault("mode_stats", {})
    if mode not in modes:
        modes[mode] = {"total": 0, "successes": 0, "avg_duration": 0.0}
    entry = modes[mode]
    entry["total"] += 1
    if success:
        entry["successes"] += 1
    # EMA para duracion
    prev_dur = entry.get("avg_duration", 0.0)
    if entry["total"] == 1:
        entry["avg_duration"] = round(duration_s, 1)
    else:
        entry["avg_duration"] = round(
            prev_dur * (1 - EMA_ALPHA) + duration_s * EMA_ALPHA, 1
        )


def _update_cross_errors(
    store: GlobalStore, validation: Optional[dict],
    project_name: str, success: bool,
):
    """Registra errores que aparecen en multiples proyectos."""
    if success or not validation or not project_name:
        return
    if validation.get("truncated"):
        store.add_cross_error("truncation", project_name)
    for issue in validation.get("issues", [])[:5]:
        issue_lower = issue.lower()
        if "innerhtml" in issue_lower:
            store.add_cross_error("innerHTML_usage", project_name)
        if "const" in issue_lower and "let" in issue_lower:
            store.add_cross_error("const_usage", project_name)


def _update_task_keywords(store: GlobalStore, task: str, success: bool):
    """Actualiza estadisticas de keywords de tarea por exito."""
    keywords = _extract_keywords(task)
    for kw in keywords[:5]:
        store.update_task_keyword(kw, success)


def _extract_keywords(text: str) -> list:
    """Extrae keywords significativos del texto."""
    text_lower = text.lower()
    words = re.findall(r'[a-z]{3,}', text_lower)
    return [w for w in words if w not in _STOP_WORDS][:8]
