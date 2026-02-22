"""Helpers para el modulo oneshot.

Funciones de utilidad para estimacion de tokens, reporte de uso
y limpieza de respuestas de DeepSeek.
"""

import math
import re


def strip_markdown_fences(text):
    """Limpia bloques de markdown que DeepSeek a veces agrega a pesar de las instrucciones.

    Maneja estos patrones:
    - ```javascript\\n...codigo...\\n```
    - ```html\\n...codigo...\\n```
    - ```\\n...codigo...\\n```
    - Texto introductorio antes del primer bloque de codigo
    """
    if not text or not text.strip():
        return text

    stripped = text.strip()

    # Caso 1: Toda la respuesta esta envuelta en un unico bloque ```lang ... ```
    fence_match = re.match(r'^```\w*\s*\n(.*?)```\s*$', stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Caso 2: Hay texto introductorio + bloque de codigo
    # "Aqui tienes el codigo:\n```javascript\n...codigo...\n```"
    intro_match = re.match(r'^[^`<{/]+?```\w*\s*\n(.*?)```\s*$', stripped, re.DOTALL)
    if intro_match:
        return intro_match.group(1).strip()

    # Caso 3: Multiples bloques de codigo — extraer contenido de todos
    blocks = re.findall(r'```\w*\s*\n(.*?)```', stripped, re.DOTALL)
    if blocks and len(blocks) >= 1:
        # Verificar que los bloques cubren la mayoria del contenido
        total_block_len = sum(len(b) for b in blocks)
        if total_block_len > len(stripped) * 0.5:
            return "\n\n".join(b.strip() for b in blocks)

    # Caso 4: Solo tiene fence de apertura sin cierre (truncado)
    if re.match(r'^```\w*\s*\n', stripped):
        return re.sub(r'^```\w*\s*\n', '', stripped).strip()

    # Sin markdown detectado, retornar tal cual
    return stripped


def estimate_tokens(text):
    """Estima tokens de un texto (~3.5 chars/token)."""
    if not text:
        return 0
    return math.ceil(len(text) / 3.5)


def build_token_usage(
    system_prompt,
    skills_context,
    surgical_briefing,
    user_prompt,
    template=None,
    context=None,
    response=None,
    global_briefing=None,
):
    """Construye reporte detallado de consumo de tokens.

    Permite a Claude Code gestionar el budget de tokens de DeepSeek (128K contexto).
    """
    sys_tokens = estimate_tokens(system_prompt)
    skills_tokens = estimate_tokens(skills_context)
    surgical_tokens = estimate_tokens(surgical_briefing)
    global_tokens = estimate_tokens(global_briefing) if global_briefing else 0
    template_tokens = estimate_tokens(template) if template else 0
    context_tokens = estimate_tokens(context) if context else 0
    prompt_tokens = estimate_tokens(user_prompt)
    response_tokens = estimate_tokens(response) if response else 0

    total_input = (
        sys_tokens + skills_tokens + surgical_tokens + global_tokens
        + template_tokens + context_tokens + prompt_tokens
    )
    total_estimated = total_input + response_tokens
    context_max = 1_000_000
    context_remaining = context_max - total_estimated

    return {
        "system_prompt": sys_tokens,
        "skills_injected": skills_tokens,
        "surgical_briefing": surgical_tokens,
        "global_briefing": global_tokens,
        "template": template_tokens,
        "context_file": context_tokens,
        "user_prompt": prompt_tokens,
        "total_input": total_input,
        "response_estimated": response_tokens,
        "total_estimated": total_estimated,
        "context_remaining": max(0, context_remaining),
        "context_used_percent": f"{total_estimated * 100 / context_max:.1f}%",
    }


# === Deteccion automatica de tipo de tarea ===
# Basada en la experiencia de Jet Combat 3D: DeepSeek recibia 20 bugs
# y reescribia todo en vez de parchear. Ahora detectamos automaticamente
# si la tarea es quirurgica (parche) o generacion (crear nuevo).


def is_surgical_task(task: str) -> bool:
    """Detecta si la tarea es de parcheo/correccion (no generacion).

    Cuando es quirurgica, DeepSeek recibe instrucciones de NO reescribir
    archivos enteros, sino devolver parches precisos.

    Args:
        task: Descripcion de la tarea

    Returns:
        True si la tarea es de correccion/parcheo
    """
    task_lower = task.lower()
    surgical_words = {
        "corrige", "corregir", "corregidos", "fix", "fixed",
        "arregla", "arreglar", "bug", "bugs",
        "parche", "parchea", "patch", "repara", "reparar", "error",
        "falla", "rompe", "broken", "crash", "problema", "issue",
        "hotfix", "debug", "soluciona", "solucion",
    }
    # Necesita al menos 1 palabra quirurgica
    has_surgical = any(word in task_lower for word in surgical_words)
    # Y NO debe ser generacion completa
    generation_words = {
        "crea desde cero", "genera completo", "nuevo proyecto",
        "from scratch", "crear nuevo",
    }
    is_generation = any(phrase in task_lower for phrase in generation_words)
    return has_surgical and not is_generation


def is_multi_file_task(task: str) -> bool:
    """Detecta si la tarea espera multiples archivos completos como respuesta.

    Args:
        task: Descripcion de la tarea

    Returns:
        True si la tarea pide multiples archivos completos
    """
    task_lower = task.lower()
    multi_file_words = {
        "todos los archivos", "cada archivo", "all files",
        "archivos corregidos", "archivos completos",
        "devuelve completo", "return complete",
        "multiple files", "multiples archivos",
    }
    return any(phrase in task_lower for phrase in multi_file_words)


def is_complex_task(task: str, template: str = None) -> bool:
    """Determina si una tarea es compleja (amerita patrones avanzados).

    Args:
        task: Descripcion de la tarea
        template: Template con TODOs (opcional)

    Returns:
        True si la tarea amerita bloques de patrones avanzados
    """
    if template and len(template) > 2000:
        return True
    task_lower = task.lower()
    complex_words = {
        "juego", "game", "sistema", "system", "arquitectura",
        "fullstack", "pipeline", "canvas", "3d", "multiplayer",
        "engine", "framework", "completo", "full",
    }
    return any(word in task_lower for word in complex_words)
