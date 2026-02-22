"""Introspective Debugger — Analisis profundo de causa raiz de fallas.

Cuando una delegacion falla, en vez de retry ciego, este modulo:
1. Correlaciona la falla con el historial de errores (SurgicalStore)
2. Identifica patrones recurrentes
3. Genera una estrategia de fix dirigida
4. Crea reglas de prevencion para el futuro

No modifica stores directamente — retorna FailureAnalysis para que
el llamador decida que hacer (guardar, retry, reportar).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class FailureAnalysis:
    """Resultado del analisis introspectivo de una falla."""
    root_cause: str           # Causa raiz identificada
    pattern: str              # Patron recurrente (key para dedup)
    fix_strategy: str         # Estrategia concreta para retry
    prevention: dict          # Regla para prevenir en futuro
    confidence: float         # 0.0-1.0
    correlations: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "pattern": self.pattern,
            "fix_strategy": self.fix_strategy,
            "prevention": self.prevention,
            "confidence": self.confidence,
            "correlations_count": len(self.correlations),
            "timestamp": datetime.now().isoformat(),
        }


# Patrones conocidos con sus causas y estrategias
KNOWN_PATTERNS = {
    "truncation": {
        "indicators": ["truncated", "incomplete", "cut_off"],
        "cause": "Respuesta truncada por exceder limite de tokens del modelo",
        "strategies": {
            "high_todos": "Dividir template en 2+ chunks con max 5 TODOs cada uno",
            "complex_task": "Simplificar la tarea o usar modo quantum (2 angulos paralelos)",
            "large_template": "Usar template_chunker con chunk_by_todos()",
            "default": "Reducir scope de la tarea o dividir en multi-step",
        },
    },
    "missing_todos": {
        "indicators": ["missing_todo", "todos_missing", "incomplete_implementation"],
        "cause": "DeepSeek omitio TODOs del template en su respuesta",
        "strategies": {
            "many_todos": "Resaltar TODOs faltantes en feedback explicito",
            "complex_todos": "Simplificar descripciones de TODOs en el template",
            "default": "Enumerar TODOs faltantes y pedir implementacion especifica",
        },
    },
    "syntax_error": {
        "indicators": ["syntax", "parse_error", "invalid_code"],
        "cause": "Codigo generado con errores de sintaxis",
        "strategies": {
            "default": "Pedir revision de sintaxis con contexto de lenguaje especifico",
        },
    },
    "innerHTML": {
        "indicators": ["innerHTML", "innerhtml", "security_hook"],
        "cause": "Uso de innerHTML bloqueado por hook de seguridad",
        "strategies": {
            "default": "Reemplazar innerHTML con textContent/DOMParser/createElement",
        },
    },
    "const_usage": {
        "indicators": ["const ", "const_instead_of_let"],
        "cause": "Uso de const en vez de let (convencion del proyecto)",
        "strategies": {
            "default": "Recordar: usar let en vez de const (regla del CLAUDE.md)",
        },
    },
}


def analyze_failure(
    store_data: Optional[dict],
    global_data: Optional[dict],
    task: str,
    validation: dict,
    response: str,
) -> FailureAnalysis:
    """Analisis profundo de causa raiz de una delegacion fallida.

    Correlaciona la falla actual con el historial completo de errores
    y genera una estrategia de fix dirigida.

    Args:
        store_data: Dict del SurgicalStore (puede ser None)
        global_data: Dict del GlobalStore (puede ser None)
        task: Descripcion de la tarea que fallo
        validation: Dict de validacion (valid, truncated, issues, etc.)
        response: Respuesta de DeepSeek que fallo

    Returns:
        FailureAnalysis con root_cause, pattern, fix_strategy, prevention
    """
    store_data = store_data or {}
    global_data = global_data or {}
    issues = validation.get("issues", [])

    # 1. Identificar el patron principal de la falla
    pattern = _identify_pattern(validation, task, response)

    # 2. Correlacionar con historial
    error_log = store_data.get("error_log", [])
    correlations = _correlate_with_history(error_log, issues, pattern)

    # 3. Correlacionar con errores cross-proyecto
    cross_errors = global_data.get("cross_project_errors", [])
    cross_corr = _correlate_cross_project(cross_errors, pattern)

    # 4. Calcular confianza basada en correlaciones
    confidence = _calculate_confidence(correlations, cross_corr, pattern)

    # 5. Generar estrategia de fix
    fix_strategy = _build_fix_strategy(pattern, validation, task, correlations)

    # 6. Generar regla de prevencion
    prevention = _build_prevention_rule(pattern, task, validation)

    # 7. Determinar causa raiz
    root_cause = _determine_root_cause(pattern, validation, correlations)

    return FailureAnalysis(
        root_cause=root_cause,
        pattern=pattern,
        fix_strategy=fix_strategy,
        prevention=prevention,
        confidence=confidence,
        correlations=correlations + cross_corr,
    )


def build_enhanced_feedback(analysis: FailureAnalysis, validation: dict) -> str:
    """Construye feedback mejorado para el retry basado en el analisis.

    Este feedback reemplaza el generico "hay N issues" con instrucciones
    especificas basadas en la causa raiz identificada.
    """
    parts = [f"ANALISIS DE FALLA (confianza: {analysis.confidence:.0%}):"]
    parts.append(f"Causa raiz: {analysis.root_cause}")
    parts.append(f"Estrategia de correccion: {analysis.fix_strategy}")

    # Agregar issues especificos de la validacion
    issues = validation.get("issues", [])
    if issues:
        parts.append(f"\nProblemas detectados ({len(issues)}):")
        for issue in issues[:5]:
            parts.append(f"  - {issue}")

    # Agregar TODOs faltantes si los hay
    missing = validation.get("todos_missing", [])
    if missing:
        parts.append(f"\nTODOs faltantes ({len(missing)}):")
        for todo in missing[:10]:
            parts.append(f"  - {todo}")

    return "\n".join(parts)


def _identify_pattern(validation: dict, task: str, response: str) -> str:
    """Identifica el patron principal de la falla actual."""
    issues_text = " ".join(validation.get("issues", [])).lower()
    is_truncated = validation.get("truncated", False)

    # Priorizar truncamiento (es el mas comun)
    if is_truncated:
        todos_found = validation.get("todos_found", 0)
        todos_missing = len(validation.get("todos_missing", []))
        if todos_missing > 5:
            return "truncation_many_todos"
        if len(response) > 50000:
            return "truncation_large_response"
        return "truncation_general"

    # Buscar patrones conocidos por indicadores
    for pattern_key, pattern_info in KNOWN_PATTERNS.items():
        for indicator in pattern_info["indicators"]:
            if indicator in issues_text:
                return pattern_key

    # Patron generico: muchos issues
    if len(validation.get("issues", [])) > 3:
        return "multiple_issues"

    return "unknown"


def _correlate_with_history(
    error_log: list,
    current_issues: list,
    current_pattern: str,
) -> List[dict]:
    """Busca errores pasados con patron similar al actual."""
    correlations = []
    issues_text = " ".join(current_issues).lower()

    for entry in reversed(error_log[-20:]):
        past_type = entry.get("type", entry.get("error_type", ""))
        past_desc = entry.get("description", entry.get("message", "")).lower()

        # Correlacion por tipo de patron
        if current_pattern in past_type or past_type in current_pattern:
            correlations.append(entry)
            continue

        # Correlacion por contenido similar
        if past_desc and issues_text:
            common_words = set(past_desc.split()) & set(issues_text.split())
            if len(common_words) >= 3:
                correlations.append(entry)

    return correlations[:5]


def _correlate_cross_project(cross_errors: list, pattern: str) -> List[dict]:
    """Busca errores cross-proyecto que correlacionen."""
    return [
        err for err in cross_errors
        if pattern in err.get("type", "") or err.get("type", "") in pattern
    ][:3]


def _calculate_confidence(
    correlations: list,
    cross_correlations: list,
    pattern: str,
) -> float:
    """Calcula confianza del analisis basada en evidencia."""
    base = 0.3  # Confianza minima

    # +0.1 por cada correlacion historica (max 0.3)
    base += min(0.3, len(correlations) * 0.1)

    # +0.1 por cada correlacion cross-proyecto (max 0.2)
    base += min(0.2, len(cross_correlations) * 0.1)

    # +0.2 si es un patron conocido
    if pattern in KNOWN_PATTERNS or pattern.startswith("truncation_"):
        base += 0.2

    return min(1.0, base)


def _build_fix_strategy(
    pattern: str,
    validation: dict,
    task: str,
    correlations: list,
) -> str:
    """Genera estrategia concreta de fix segun el patron identificado."""
    # Estrategias para truncamiento
    if pattern.startswith("truncation_"):
        todos_total = validation.get("todos_found", 0) + len(validation.get("todos_missing", []))
        if todos_total > 8:
            return (f"Template tiene {todos_total} TODOs. Dividir en 2 chunks "
                    f"de ~{todos_total // 2} TODOs cada uno usando template_chunker.")
        if pattern == "truncation_large_response":
            return "Respuesta excesivamente larga. Simplificar tarea o usar quantum dual."
        return "Reducir complejidad de la tarea. Considerar multi-step con pasos mas pequeños."

    # Estrategias de patrones conocidos
    base_pattern = pattern.split("_")[0] if "_" in pattern else pattern
    if base_pattern in KNOWN_PATTERNS:
        strategies = KNOWN_PATTERNS[base_pattern]["strategies"]
        # Seleccionar sub-estrategia mas relevante
        for sub_key, strategy in strategies.items():
            if sub_key != "default" and sub_key in pattern:
                return strategy
        return strategies.get("default", "Revisar y corregir manualmente.")

    # Estrategia basada en correlaciones (aprender del pasado)
    if correlations:
        past_fixes = [c.get("fix_applied", "") for c in correlations if c.get("fix_applied")]
        if past_fixes:
            return f"Fix historico exitoso: {past_fixes[0]}"

    return "Analizar issues individuales y corregir uno por uno."


def _build_prevention_rule(pattern: str, task: str, validation: dict) -> dict:
    """Genera regla de prevencion para el SurgicalStore."""
    rule = {
        "pattern": pattern,
        "trigger": "",
        "action": "",
        "created_from": "introspective_debugger",
    }

    if pattern.startswith("truncation_"):
        todos = validation.get("todos_found", 0) + len(validation.get("todos_missing", []))
        rule["trigger"] = f"template_with_{todos}+_todos"
        rule["action"] = "auto_chunk_template"
    elif pattern == "innerHTML":
        rule["trigger"] = "code_with_innerHTML"
        rule["action"] = "reject_and_suggest_alternatives"
    elif pattern == "const_usage":
        rule["trigger"] = "code_with_const"
        rule["action"] = "remind_let_convention"
    else:
        rule["trigger"] = f"task_matching_{pattern}"
        rule["action"] = "apply_enhanced_feedback"

    return rule


def _determine_root_cause(
    pattern: str,
    validation: dict,
    correlations: list,
) -> str:
    """Determina la causa raiz legible para el reporte."""
    if pattern.startswith("truncation_"):
        base = KNOWN_PATTERNS["truncation"]["cause"]
        todos = validation.get("todos_found", 0) + len(validation.get("todos_missing", []))
        if todos > 8:
            return f"{base} (template con {todos} TODOs excede capacidad de respuesta)"
        return base

    base_key = pattern.split("_")[0] if "_" in pattern else pattern
    if base_key in KNOWN_PATTERNS:
        return KNOWN_PATTERNS[base_key]["cause"]

    if correlations:
        return f"Error recurrente del tipo '{pattern}' ({len(correlations)} ocurrencias previas)"

    return f"Falla de tipo '{pattern}' sin historial previo"
