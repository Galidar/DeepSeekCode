"""Validador de respuestas de delegacion DeepSeek.

Detecta truncamiento, TODOs faltantes, y errores comunes.
Genera feedback automatico para retry si la respuesta tiene problemas.
"""

import re


def validate_delegate_response(response, template=None):
    """Valida la respuesta de DeepSeek y retorna diagnostico.

    Args:
        response: Texto de respuesta de DeepSeek
        template: Template original con TODOs (opcional)

    Returns:
        dict con: valid (bool), issues (list), todos_found (list),
        todos_missing (list), stats (dict), feedback (str o None)
    """
    result = {
        "valid": True,
        "issues": [],
        "todos_found": [],
        "todos_missing": [],
        "stats": {},
        "feedback": None,
        "truncated": False,
    }

    if not response or len(response.strip()) < 20:
        result["valid"] = False
        result["issues"].append("Respuesta vacia o demasiado corta")
        result["feedback"] = "Tu respuesta fue vacia. Genera todo el codigo."
        return result

    # --- Detectar truncamiento ---
    truncation_signs = _detect_truncation(response)
    if truncation_signs:
        result["truncated"] = True
        result["issues"].extend(truncation_signs)

    # --- Verificar TODOs completados vs template ---
    if template:
        template_todos = _extract_todos_from_template(template)
        found_todos = _extract_todos_from_response(response)
        result["todos_found"] = found_todos
        missing = [t for t in template_todos if t not in found_todos]
        result["todos_missing"] = missing

        if missing:
            result["valid"] = False
            result["issues"].append(
                f"TODOs faltantes: {', '.join(missing)}"
            )

    # --- Detectar errores comunes de Canvas ---
    canvas_errors = _detect_canvas_errors(response)
    if canvas_errors:
        result["issues"].extend(canvas_errors)

    # --- Estadisticas ---
    lines = response.strip().split('\n')
    result["stats"] = {
        "lines": len(lines),
        "chars": len(response),
        "functions": len(re.findall(r'function\s+\w+', response)),
        "todos_total": len(result.get("todos_found", [])),
        "estimated_tokens": len(response) // 4,
    }

    # --- Generar feedback para retry ---
    if not result["valid"] or result["truncated"]:
        result["feedback"] = _build_feedback(result)

    return result


def estimate_template_tokens(template):
    """Estima cuantos tokens usa el template para decidir si hacer split.

    Returns:
        dict con: chars, estimated_tokens, recommended_split (bool),
        suggested_splits (list de listas de TODOs)
    """
    chars = len(template)
    estimated_tokens = chars // 4
    todos = _extract_todos_from_template(template)

    # Si el template tiene mas de ~3000 tokens de TODOs,
    # se recomienda dividir en 2 delegaciones
    # DeepSeek tiene ~4K tokens de respuesta max (~16K chars)
    # Con el system prompt (~7K tokens), quedan ~9K para respuesta
    # Safety margin: recomendar split si >8 TODOs o >3000 chars de template
    recommend_split = len(todos) > 8 or chars > 3000

    splits = []
    if recommend_split and len(todos) >= 4:
        mid = len(todos) // 2
        splits = [todos[:mid], todos[mid:]]

    return {
        "chars": chars,
        "estimated_tokens": estimated_tokens,
        "todo_count": len(todos),
        "todos": todos,
        "recommended_split": recommend_split,
        "suggested_splits": splits,
    }


def _detect_truncation(response):
    """Detecta senales de que la respuesta fue truncada."""
    signs = []
    lines = response.strip().split('\n')
    if not lines:
        return ["Respuesta vacia"]

    last_line = lines[-1].strip()

    # Linea incompleta (no termina en ; } ) o comentario)
    if last_line and not re.search(r'[;}\)\]\'\"\/]$', last_line):
        if not last_line.startswith('//') and not last_line.startswith('/*'):
            signs.append(f"Ultima linea incompleta: '{last_line[:60]}...'")

    # Llaves sin cerrar
    open_braces = response.count('{') - response.count('}')
    if open_braces > 2:
        signs.append(f"Llaves sin cerrar: {open_braces} abiertas")

    # Parentesis sin cerrar
    open_parens = response.count('(') - response.count(')')
    if open_parens > 2:
        signs.append(f"Parentesis sin cerrar: {open_parens} abiertos")

    # Funcion abierta sin cierre
    if re.search(r'function\s+\w+\s*\([^)]*\)\s*\{[^}]*$', response[-200:]):
        signs.append("Ultima funcion parece truncada")

    return signs


def _extract_todos_from_template(template):
    """Extrae nombres de TODO del template.

    Busca patrones como:
      // === TODO 1A: renderPlayer(ctx) ===
      /* TODO: ENEMY_TYPES */
      // === TODO 1K: initAudio() + resumeAudio() + playSound(type) ===
    """
    todos = []
    # Palabras que son titulos de seccion, no funciones/variables
    _noise = {
        'datos', 'rendering', 'audio', 'ui', 'efectos',
        'logica', 'sistema', 'con', 'del', 'ctx',
    }
    # Patron: "TODO 1A: renderPlayer" -> "renderPlayer"
    for match in re.finditer(
        r'TODO\s+[\dA-Za-z]+\s*:\s*(\w+)',
        template,
    ):
        name = match.group(1)
        if name.lower() not in _noise:
            todos.append(name)

    # Fallback: /* TODO: nombre */ (sin ID)
    if not todos:
        for match in re.finditer(
            r'/\*\s*TODO:\s*(\w+)\s*\*/',
            template,
        ):
            todos.append(match.group(1))

    # Deduplicate preservando orden
    seen = set()
    unique = []
    for t in todos:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return unique


def _extract_todos_from_response(response):
    """Extrae que TODOs fueron implementados en la respuesta."""
    found = []

    # Busca funciones definidas
    for match in re.finditer(r'function\s+(\w+)', response):
        found.append(match.group(1))

    # Busca variables/objetos definidos (let/var ENEMY_TYPES = ...)
    for match in re.finditer(r'(?:let|var)\s+(\w+)\s*=', response):
        name = match.group(1)
        if name[0].isupper() or '_' in name:  # Solo constantes/objetos
            found.append(name)

    seen = set()
    unique = []
    for f in found:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    return unique


def _detect_canvas_errors(response):
    """Detecta errores comunes de Canvas 2D."""
    errors = []

    # save sin restore
    saves = len(re.findall(r'ctx\.save\(\)', response))
    restores = len(re.findall(r'ctx\.restore\(\)', response))
    if saves > restores + 1:
        errors.append(
            f"Posible ctx.save() sin restore ({saves} saves, {restores} restores)"
        )

    # innerHTML (prohibido)
    if 'innerHTML' in response:
        errors.append("Usa innerHTML (prohibido por reglas de seguridad)")

    # const en vez de let
    consts = len(re.findall(r'\bconst\b', response))
    if consts > 3:
        errors.append(f"Usa 'const' {consts} veces (debe usar 'let')")

    # Propiedades abreviadas de estrella
    if re.search(r'\bs\.(b|z|r)\b', response):
        if 'star' in response.lower() or 'estrella' in response.lower():
            errors.append(
                "Usa propiedades abreviadas de estrella (s.b, s.z) "
                "en vez de s.brightness, s.size"
            )

    # Variables declaradas pero nunca usadas
    declared_vars = re.findall(r'let\s+(\w+)\s*=', response)
    for var in declared_vars:
        # Contar menciones: la declaracion + usos
        mentions = len(re.findall(r'\b' + re.escape(var) + r'\b', response))
        if mentions <= 1 and var not in ('_', 'i', 'j', 'k'):
            errors.append(f"Variable '{var}' declarada pero nunca usada")

    # Turret con speed: 0 pero usa e.speed para moverse
    if re.search(r'speed:\s*0', response):
        if re.search(r'e\.vy\s*=\s*e\.speed', response):
            errors.append(
                "Enemigo con speed:0 usa e.speed para moverse (sera 0, "
                "nunca se movera). Usa valor hardcoded."
            )

    return errors


def _build_feedback(result):
    """Construye mensaje de feedback para retry automatico."""
    parts = []

    if result["truncated"]:
        parts.append(
            "Tu respuesta fue TRUNCADA (cortada). "
            "Sé mas CONCISO: funciones mas cortas, sin comentarios "
            "largos, sin repetir codigo del template."
        )

    if result["todos_missing"]:
        parts.append(
            f"Te faltan estos TODOs: {', '.join(result['todos_missing'])}. "
            "Implementalos TODOS."
        )

    if result["issues"]:
        non_todo_issues = [
            i for i in result["issues"]
            if "TODO" not in i and "trunca" not in i.lower()
        ]
        if non_todo_issues:
            parts.append(
                "Errores detectados: " + "; ".join(non_todo_issues)
            )

    return " ".join(parts) if parts else None
