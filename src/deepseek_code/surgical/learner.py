"""Motor de aprendizaje para SurgicalMemory.

Analiza resultados de delegaciones para extraer reglas, patrones,
y convenciones que mejoran futuras delegaciones.
"""

import re
from typing import Optional


def learn_from_delegation(
    store,
    task: str,
    mode: str,
    success: bool,
    response: str,
    validation: Optional[dict] = None,
    duration_s: float = 0.0,
):
    """Analiza una delegacion completada y actualiza el store.

    Punto de entrada principal. Registra el historial, extrae errores
    si los hay, y descubre patrones exitosos.

    Args:
        store: SurgicalStore del proyecto
        task: Tarea ejecutada
        mode: Modo de delegacion
        success: Si la respuesta fue valida
        response: Respuesta de DeepSeek
        validation: Resultado de validate_delegate_response
        duration_s: Duracion en segundos
    """
    from .collector import build_delegation_record, extract_error_entry

    # 1. Registrar en historial
    record = build_delegation_record(
        task, mode, success, duration_s,
        validation=validation,
        response_stats=validation.get("stats") if validation else None,
    )
    store.add_delegation(record)

    # 2. Si hubo errores, registrar y aprender reglas
    if validation and not success:
        error_entry = extract_error_entry(validation, task)
        if error_entry:
            store.add_error(error_entry)
        _learn_rules_from_failure(store, task, validation)

    # 3. Si fue exitoso, extraer patrones
    if success and response:
        _learn_patterns_from_success(store, task, response)

    # 4. Detectar convenciones del codigo generado
    if success and response:
        _detect_conventions(store, response)

    store.save()


def _learn_rules_from_failure(store, task: str, validation: dict):
    """Extrae reglas de una delegacion fallida."""
    if validation.get("truncated"):
        store.add_feedback_rule({
            "trigger": "truncation",
            "action": "Este tipo de tarea genera respuestas truncadas. "
                     "Dividir en 2 delegaciones o simplificar el template.",
            "task_keywords": _extract_keywords(task),
        })

    missing = validation.get("todos_missing", [])
    if len(missing) > 3:
        store.add_feedback_rule({
            "trigger": "many_missing_todos",
            "action": f"Templates con +{len(missing)} TODOs tienden a fallar. "
                     "Dividir en 2 delegaciones.",
            "task_keywords": _extract_keywords(task),
        })
    elif missing:
        for todo_name in missing[:3]:
            store.add_feedback_rule({
                "trigger": f"missing_todo_{todo_name}",
                "action": f"La funcion '{todo_name}' tiende a faltar. "
                         "Dar mas contexto sobre su API y comportamiento esperado.",
            })

    # Detectar errores especificos de codigo
    issues = validation.get("issues", [])
    seen_triggers = set()
    for issue in issues:
        issue_lower = issue.lower()
        if "innerhtml" in issue_lower and "innerHTML_usage" not in seen_triggers:
            seen_triggers.add("innerHTML_usage")
            store.add_feedback_rule({
                "trigger": "innerHTML_usage",
                "action": "NUNCA usar innerHTML. Usar textContent o createElement.",
            })
        if "const" in issue_lower and "let" in issue_lower and "const_usage" not in seen_triggers:
            seen_triggers.add("const_usage")
            store.add_feedback_rule({
                "trigger": "const_usage",
                "action": "Usar let en vez de const (regla del proyecto).",
            })
        if "save" in issue_lower and "restore" in issue_lower and "save_restore" not in seen_triggers:
            seen_triggers.add("save_restore")
            store.add_feedback_rule({
                "trigger": "save_restore_mismatch",
                "action": "ctx.save() y ctx.restore() DEBEN estar en pares.",
            })
        if "duplica" in issue_lower and "var_duplicate" not in seen_triggers:
            seen_triggers.add("var_duplicate")
            store.add_feedback_rule({
                "trigger": "quantum_var_duplicate",
                "action": "En modo quantum, cada angulo debe declarar SOLO "
                         "sus variables exclusivas. Variables compartidas (canvas, "
                         "ctx, player) deben declararse en UN solo angulo.",
            })


def _learn_patterns_from_success(store, task: str, response: str):
    """Extrae patrones de una delegacion exitosa."""
    keywords = _extract_keywords(task)

    # Detectar funciones definidas como patrones
    functions = re.findall(r'function\s+(\w+)\s*\(([^)]*)\)', response)
    if functions:
        func_list = [f"{name}({args})" for name, args in functions[:10]]
        pattern_name = f"success_{keywords[0]}" if keywords else "success_generic"
        store.add_pattern({
            "name": pattern_name,
            "description": f"Funciones exitosas: {', '.join(func_list[:5])}",
            "keywords": keywords,
            "function_signatures": func_list,
        })

    # Detectar si uso audio procedural
    if "playSound" in response or "AudioContext" in response:
        store.add_pattern({
            "name": "audio_pattern",
            "description": "Implementacion de audio procedural exitosa",
            "keywords": ["audio", "sound", "sonido"],
        })


def _detect_conventions(store, response: str):
    """Detecta convenciones de codigo de la respuesta."""
    # Detectar estilo de naming
    camel_count = len(re.findall(r'\b[a-z]+[A-Z]\w+\b', response))
    snake_count = len(re.findall(r'\b[a-z]+_[a-z]+\b', response))
    if camel_count > snake_count * 2:
        store.set_conventions(naming="camelCase")
    elif snake_count > camel_count * 2:
        store.set_conventions(naming="snake_case")

    # Detectar uso de let vs const
    let_count = len(re.findall(r'\blet\b', response))
    const_count = len(re.findall(r'\bconst\b', response))
    if let_count > 0 and const_count == 0:
        store.set_conventions(patterns="let-only (no const)")


def _extract_keywords(text: str) -> list:
    """Extrae keywords significativos del texto de la tarea."""
    text_lower = text.lower()
    # Palabras comunes a ignorar
    stop_words = {
        "el", "la", "los", "las", "un", "una", "de", "del", "que",
        "en", "con", "para", "por", "todo", "todos", "cada", "como",
        "the", "a", "an", "of", "to", "and", "or", "for", "in",
        "implementar", "implement", "crear", "create", "hacer", "make",
        "codigo", "code", "funcion", "function", "que", "sea", "debe",
    }
    words = re.findall(r'[a-z]{3,}', text_lower)
    return [w for w in words if w not in stop_words][:8]
