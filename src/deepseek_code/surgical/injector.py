"""Inyector de memoria quirurgica en el system prompt de delegacion.

Selecciona las secciones mas relevantes del SurgicalStore y construye
un briefing compacto que se agrega al enriched_system de cada modo.
Respeta un budget de tokens configurable.
"""

from typing import Optional


# Budget de tokens para el briefing (1M context → budgets proporcionales)
DEFAULT_TOKEN_BUDGET = 15000
MIN_TOKEN_BUDGET = 5000
MAX_TOKEN_BUDGET = 25000


def _estimate_tokens(text: str) -> int:
    """Estima tokens de un texto (~3.5 chars/token)."""
    return max(1, len(text) // 4)


def build_briefing(
    store_data: dict,
    task: str,
    claude_md_content: Optional[str] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> str:
    """Construye el briefing contextual para inyectar en el system prompt.

    Selecciona secciones del store ordenadas por prioridad, hasta llenar
    el budget de tokens. Las secciones se formatean de forma compacta.

    Args:
        store_data: Datos del SurgicalStore
        task: Tarea actual (para filtrar contenido relevante)
        claude_md_content: Contenido de CLAUDE.md (opcional)
        token_budget: Tokens maximos para el briefing

    Returns:
        String formateado listo para agregar al system prompt, o ""
    """
    budget = max(MIN_TOKEN_BUDGET, min(MAX_TOKEN_BUDGET, token_budget))
    sections = []
    used_tokens = 0

    header = "\n\n== CONTEXTO DEL PROYECTO (SurgicalMemory) ==\n"
    used_tokens += _estimate_tokens(header)

    # 1. Feedback rules (maxima prioridad)
    text = _format_feedback_rules(store_data, task)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 2. Errores recientes relevantes
    text = _format_recent_errors(store_data, task)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 3. Convenciones del proyecto
    text = _format_conventions(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 4. Arquitectura
    text = _format_architecture(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 5. Patrones exitosos
    text = _format_patterns(store_data, task)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 5.5 Intelligence: Shadow corrections + failure analyses
    text = _format_intelligence_data(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 6. CLAUDE.md (si hay presupuesto)
    if claude_md_content:
        remaining = budget - used_tokens
        if remaining > 200:
            max_chars = remaining * 4  # ~4 chars/token
            truncated = claude_md_content[:max_chars]
            if len(claude_md_content) > max_chars:
                truncated += "\n[... truncado ...]"
            text = f"\nDOCUMENTACION DEL PROYECTO:\n{truncated}\n"
            sections.append(text)

    if not sections:
        return ""

    footer = "== FIN CONTEXTO PROYECTO ==\n"
    return header + "\n".join(sections) + "\n" + footer


def _format_feedback_rules(store_data: dict, task: str) -> str:
    """Formatea reglas aprendidas de feedback, priorizando las relevantes."""
    rules = store_data.get("feedback_rules", [])
    if not rules:
        return ""

    # Ordenar por ocurrencias (mas frecuentes primero)
    sorted_rules = sorted(
        rules, key=lambda r: r.get("occurrences", 0), reverse=True
    )

    lines = ["REGLAS APRENDIDAS (errores pasados a evitar):"]
    for rule in sorted_rules[:8]:
        trigger = rule.get("trigger", "")
        action = rule.get("action", "")
        occurrences = rule.get("occurrences", 1)
        lines.append(f"- [{occurrences}x] {trigger}: {action}")

    return "\n".join(lines) + "\n"


def _format_recent_errors(store_data: dict, task: str) -> str:
    """Formatea errores recientes."""
    errors = store_data.get("error_log", [])
    if not errors:
        return ""

    recent = errors[-5:]
    lines = ["ERRORES RECIENTES (evitar repetir):"]
    for err in reversed(recent):
        err_type = err.get("type", "unknown")
        issues = err.get("issues", [])
        summary = "; ".join(issues[:2]) if issues else err_type
        lines.append(f"- {err_type}: {summary}")

    return "\n".join(lines) + "\n"


def _format_conventions(store_data: dict) -> str:
    """Formatea convenciones del proyecto."""
    conv = store_data.get("conventions", {})
    if not conv or not any(conv.values()):
        return ""

    lines = ["CONVENCIONES DEL PROYECTO:"]
    for key in ("naming", "imports", "patterns", "custom_rules"):
        value = conv.get(key)
        if value:
            if isinstance(value, list):
                for item in value[:5]:
                    lines.append(f"- {item}")
            else:
                lines.append(f"- {key}: {value}")

    return "\n".join(lines) + "\n"


def _format_architecture(store_data: dict) -> str:
    """Formatea informacion de arquitectura del proyecto."""
    arch = store_data.get("architecture", {})
    desc = arch.get("description", "")
    struct = arch.get("structure", "")
    if not desc and not struct:
        return ""

    lines = ["ARQUITECTURA DEL PROYECTO:"]
    if desc:
        lines.append(desc[:5000])
    if struct:
        lines.append(struct[:5000])

    decisions = arch.get("key_decisions", [])
    for d in decisions[:5]:
        lines.append(f"- {d}")

    return "\n".join(lines) + "\n"


def _format_patterns(store_data: dict, task: str) -> str:
    """Formatea patrones exitosos relevantes a la tarea."""
    patterns = store_data.get("patterns", [])
    if not patterns:
        return ""

    task_lower = task.lower()
    relevant = []
    for p in patterns:
        name = p.get("name", "").lower()
        keywords = p.get("keywords", [])
        if any(kw in task_lower for kw in keywords) or name in task_lower:
            relevant.append(p)

    # Si no hay relevantes, mostrar los mas usados
    if not relevant:
        relevant = sorted(
            patterns, key=lambda x: x.get("use_count", 0), reverse=True
        )[:3]

    if not relevant:
        return ""

    lines = ["PATRONES EXITOSOS:"]
    for p in relevant[:5]:
        name = p.get("name", "unnamed")
        desc = p.get("description", "")
        lines.append(f"- {name}: {desc}")

    return "\n".join(lines) + "\n"


def _format_intelligence_data(store_data: dict) -> str:
    """Formatea datos del Intelligence Package (shadow corrections + analyses)."""
    parts = []

    # Shadow corrections aprendidas del usuario
    corrections = store_data.get("shadow_corrections", [])
    significant = [c for c in corrections if c.get("frequency", 0) >= 2]
    if significant:
        significant.sort(key=lambda x: x.get("frequency", 0), reverse=True)
        lines = ["CORRECCIONES APRENDIDAS DEL USUARIO:"]
        for c in significant[:5]:
            freq = c.get("frequency", 0)
            desc = c.get("description", "sin descripcion")
            lines.append(f"- [{freq}x] {desc}")
        parts.append("\n".join(lines))

    # Reglas de prevencion de failure analyses
    analyses = store_data.get("failure_analyses", [])
    preventions = [a for a in analyses if a.get("prevention")]
    if preventions:
        lines = ["REGLAS DE PREVENCION (aprendidas de fallas):"]
        for a in preventions[-3:]:
            pattern = a.get("pattern", "?")
            prevention = a.get("prevention", {})
            action = prevention.get("action", "?")
            lines.append(f"- {pattern} -> {action}")
        parts.append("\n".join(lines))

    if not parts:
        return ""
    return "\n".join(parts) + "\n"
