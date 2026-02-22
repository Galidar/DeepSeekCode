"""Inyector de memoria global en el system prompt de delegacion.

Construye un briefing compacto (~2000 tokens max) con el perfil personal
del usuario: estilo de codigo, skills efectivas, complejidad optima,
errores recurrentes, y rendimiento por modo.
"""


# Budget de tokens para el briefing global
DEFAULT_BUDGET = 2000
MIN_BUDGET = 500
MAX_BUDGET = 3000

# Minimo de inyecciones para que una skill sea significativa
MIN_SKILL_SAMPLES = 3


def _estimate_tokens(text: str) -> int:
    """Estima tokens de un texto (~4 chars/token)."""
    return max(1, len(text) // 4)


def build_global_briefing(store_data: dict, token_budget: int = DEFAULT_BUDGET) -> str:
    """Construye el briefing del perfil personal del desarrollador.

    Selecciona secciones por prioridad hasta llenar el budget.

    Args:
        store_data: Datos del GlobalStore
        token_budget: Tokens maximos para el briefing

    Returns:
        String formateado o "" si no hay datos suficientes
    """
    total_delegations = store_data.get("total_delegations", 0)
    if total_delegations < 2:
        return ""

    budget = max(MIN_BUDGET, min(MAX_BUDGET, token_budget))
    sections = []
    used_tokens = 0

    header = "\n\n== PERFIL PERSONAL DEL DESARROLLADOR (GlobalMemory) ==\n"
    used_tokens += _estimate_tokens(header)

    # 1. Estilo de codigo (siempre, ~100 tokens)
    text = _format_code_style(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 2. Skills recomendadas/evitar (~200 tokens)
    text = _format_skill_recommendations(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 3. Errores cross-proyecto (~200 tokens)
    text = _format_cross_errors(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 4. Complejidad optima (~150 tokens)
    text = _format_complexity(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    # 5. Modo recomendado (~150 tokens)
    text = _format_mode_recommendation(store_data)
    if text:
        tokens = _estimate_tokens(text)
        if used_tokens + tokens <= budget:
            sections.append(text)
            used_tokens += tokens

    if not sections:
        return ""

    footer = "== FIN PERFIL PERSONAL ==\n"
    return header + "\n".join(sections) + "\n" + footer


def _format_code_style(store_data: dict) -> str:
    """Formatea preferencias de estilo de codigo."""
    style = store_data.get("code_style", {})
    total_vars = style.get("let_count", 0) + style.get("const_count", 0)
    if total_vars < 5:
        return ""

    parts = ["ESTILO DE CODIGO:"]
    # let vs const
    if style.get("let_preference", True):
        pct = round(style["let_count"] * 100 / total_vars) if total_vars else 0
        parts.append(f"- Usar let (no const) — {pct}% de preferencia historica")
    else:
        pct = round(style["const_count"] * 100 / total_vars) if total_vars else 0
        parts.append(f"- Usar const — {pct}% de preferencia historica")

    # Naming
    naming = style.get("naming_preference", "")
    if naming:
        parts.append(f"- Naming: {naming}")

    # Idioma
    lang = style.get("comment_lang", "")
    if lang:
        lang_name = "espanol" if lang == "es" else "ingles"
        parts.append(f"- Comentarios en {lang_name}")

    return "\n".join(parts) + "\n"


def _format_skill_recommendations(store_data: dict) -> str:
    """Formatea skills recomendadas y a evitar por tasa de exito real."""
    stats = store_data.get("skill_stats", {})
    if not stats:
        return ""

    # Filtrar skills con suficientes muestras
    significant = {
        name: st for name, st in stats.items()
        if st.get("injected", 0) >= MIN_SKILL_SAMPLES
    }
    if not significant:
        return ""

    # Top 5 por success_rate
    top = sorted(
        significant.items(),
        key=lambda x: x[1].get("success_rate", 0), reverse=True,
    )[:5]

    # Skills a evitar (success_rate < 0.4 o truncation rate > 0.5)
    avoid = []
    for name, st in significant.items():
        rate = st.get("success_rate", 1.0)
        trunc_rate = st.get("with_truncation", 0) / max(1, st.get("injected", 1))
        if rate < 0.4 or trunc_rate > 0.5:
            avoid.append((name, rate, trunc_rate))

    if not top and not avoid:
        return ""

    parts = ["SKILLS RECOMENDADAS (por tasa de exito real):"]
    for name, st in top:
        rate = st.get("success_rate", 0)
        injected = st.get("injected", 0)
        parts.append(f"- {name}: {rate:.0%} exito ({injected} usos)")

    if avoid:
        parts.append("EVITAR:")
        for name, rate, trunc in avoid[:3]:
            reason = f"{rate:.0%} exito"
            if trunc > 0.3:
                reason += f", trunca {trunc:.0%}"
            parts.append(f"- {name} ({reason})")

    return "\n".join(parts) + "\n"


def _format_cross_errors(store_data: dict) -> str:
    """Formatea errores recurrentes cross-proyecto."""
    errors = store_data.get("cross_project_errors", [])
    # Solo mostrar errores que aparecen en 2+ proyectos o 3+ veces
    significant = [
        e for e in errors
        if len(e.get("projects", [])) >= 2 or e.get("count", 0) >= 3
    ]
    if not significant:
        return ""

    sorted_errors = sorted(significant, key=lambda x: x.get("count", 0), reverse=True)
    parts = ["ERRORES RECURRENTES (cross-proyecto):"]
    for err in sorted_errors[:5]:
        err_type = err.get("type", "unknown")
        count = err.get("count", 0)
        projects = err.get("projects", [])
        parts.append(f"- {err_type}: {count}x en {len(projects)} proyecto(s)")

    return "\n".join(parts) + "\n"


def _format_complexity(store_data: dict) -> str:
    """Formatea estadisticas de complejidad optima."""
    comp = store_data.get("complexity_stats", {})
    samples = comp.get("successful_samples", 0)
    if samples < 3:
        return ""

    parts = ["COMPLEJIDAD OPTIMA:"]
    sweet_todos = comp.get("sweet_spot_todos", 5)
    sweet_tokens = comp.get("sweet_spot_input_tokens", 40000)
    parts.append(f"- TODOs por template: {sweet_todos} (sweet spot historico)")
    parts.append(f"- Input tokens optimo: ~{sweet_tokens:,}")

    return "\n".join(parts) + "\n"


def _format_mode_recommendation(store_data: dict) -> str:
    """Formatea recomendacion de modo por rendimiento."""
    modes = store_data.get("mode_stats", {})
    if not modes:
        return ""

    # Solo mostrar modos con suficientes muestras
    significant = {
        name: st for name, st in modes.items()
        if st.get("total", 0) >= 2
    }
    if not significant:
        return ""

    parts = ["RENDIMIENTO POR MODO:"]
    for name, st in sorted(
        significant.items(),
        key=lambda x: x[1].get("successes", 0) / max(1, x[1].get("total", 1)),
        reverse=True,
    ):
        total = st.get("total", 0)
        successes = st.get("successes", 0)
        rate = successes / max(1, total)
        avg_dur = st.get("avg_duration", 0)
        parts.append(
            f"- {name}: {rate:.0%} exito ({total} usos, ~{avg_dur:.0f}s promedio)"
        )

    return "\n".join(parts) + "\n"
