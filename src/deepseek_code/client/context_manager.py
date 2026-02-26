"""Gestion de contexto y resumen progresivo para DeepSeekCodeClient.

Contiene la logica de estimacion de tokens, resumen de mensajes
y compresion progresiva del historial.
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Re-exportar constante para uso interno
SUMMARY_MAX_TOKENS = 2048


def estimate_tokens(text: str) -> int:
    """Estima tokens a partir del largo del texto (~3.5 chars/token)."""
    return math.ceil(len(text) / 3.5)


def total_estimated_tokens(conversation_history: List[Dict]) -> int:
    """Calcula tokens estimados de todo el historial."""
    total = 0
    for msg in conversation_history:
        content = msg.get("content", "")
        if content:
            total += estimate_tokens(content)
    return total


def build_summary_prompt(messages: List[Dict]) -> str:
    """Construye el prompt para solicitar un resumen al modelo."""
    prompt = (
        "Resume la conversacion siguiente de forma concisa pero completa. "
        "Conserva: preferencias del usuario, decisiones tomadas, datos importantes, "
        "archivos modificados, errores encontrados y soluciones. "
        "Omite: saludos, confirmaciones triviales, repeticiones.\n\n"
        "Conversacion:\n"
    )
    for msg in messages:
        role_map = {"user": "Usuario", "assistant": "Asistente", "tool": "Herramienta", "tool_result": "Herramienta"}
        role = role_map.get(msg["role"], msg["role"])
        content = msg.get("content", "") or ""
        # Truncar resultados de herramientas muy largos
        if msg["role"] in ("tool", "tool_result") and len(content) > 10000:
            content = content[:10000] + "... [truncado]"
        prompt += f"{role}: {content}\n"
    prompt += "\nResumen estructurado:"
    return prompt


def should_summarize(
    conversation_history: List[Dict],
    max_context_tokens: int,
    summary_threshold: int,
    summary_count: int,
    max_summaries: int
) -> Optional[Tuple[List[Dict], List[Dict]]]:
    """Determina si se debe resumir y retorna (to_summarize, to_keep) o None.

    Retorna None si no es necesario resumir.
    Retorna (mensajes_a_resumir, mensajes_a_conservar) si si.
    """
    total_tokens = total_estimated_tokens(conversation_history)
    threshold_tokens = int(max_context_tokens * summary_threshold / 100)

    if total_tokens < threshold_tokens:
        return None

    if summary_count >= max_summaries:
        return None

    # Separar system message del resto
    non_system = [m for m in conversation_history if m["role"] != "system"]
    if len(non_system) < 4:
        return None

    # Dividir: primera mitad se resume, segunda mitad se conserva intacta
    split_point = len(non_system) // 2
    # Ajustar split para no cortar en medio de un tool_call/tool_result
    while split_point < len(non_system) - 1 and non_system[split_point]["role"] in ("tool", "tool_result"):
        split_point += 1

    to_summarize = non_system[:split_point]
    to_keep = non_system[split_point:]

    return to_summarize, to_keep


def rebuild_history_after_summary(
    system_message: str,
    summary: str,
    to_keep: List[Dict]
) -> List[Dict]:
    """Reconstruye el historial despues de un resumen progresivo."""
    history = [{"role": "system", "content": system_message}]
    # Inyectar resumen como mensaje del asistente para dar contexto
    history.append({
        "role": "assistant",
        "content": f"[Contexto previo resumido]: {summary}"
    })
    # Mantener mensajes recientes intactos
    history.extend(to_keep)
    return history


def make_memory_entry(summary: str) -> str:
    """Crea una entrada de memoria con timestamp para guardar el resumen."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"\n## Resumen de conversacion ({timestamp})\n{summary}\n"


def format_summary_notification(
    summary_count: int,
    to_summarize_count: int,
    tokens_before: int,
    tokens_after: int,
    max_context_tokens: int
) -> str:
    """Genera el mensaje de notificacion del resumen progresivo."""
    tokens_freed = tokens_before - tokens_after
    return (
        f"**Resumen progresivo #{summary_count}**: "
        f"Se comprimieron {to_summarize_count} mensajes antiguos "
        f"({tokens_freed:,} tokens liberados). "
        f"Contexto actual: {tokens_after:,}/{max_context_tokens:,} tokens "
        f"({tokens_after * 100 // max_context_tokens}%)"
    )
