"""Logica centralizada de llamadas API para DeepSeek V3.2.

Centraliza la seleccion de modelo y max_tokens que antes estaba
duplicada en deepseek_client.py. Basado en capacidades reales:

- deepseek-chat (V3.2 non-thinking): 128K contexto, 8K output max
- deepseek-reasoner (V3.2 thinking): 128K contexto, 64K output max

Para tareas de codigo complejas (CODE_COMPLEX, DELEGATION),
auto-selecciona deepseek-reasoner que da 8x mas output y razona.
"""

import sys
from typing import Dict, List, Optional

from .task_classifier import TaskLevel

# Modelos disponibles en DeepSeek V3.2
MODEL_CHAT = "deepseek-chat"
MODEL_REASONER = "deepseek-reasoner"

# Max tokens de OUTPUT por nivel de tarea
# Chat/Simple: poco output, rapido
# Code: mas output para generar codigo
# Delegation: maximo output para archivos completos
MAX_TOKENS_MAP = {
    TaskLevel.CHAT: 1024,
    TaskLevel.SIMPLE: 2048,
    TaskLevel.CODE_SIMPLE: 4096,
    TaskLevel.CODE_COMPLEX: 8192,
    TaskLevel.DELEGATION: 16384,
}


def select_model_for_task(
    base_model: str,
    task_level: TaskLevel,
    auto_select: bool = True,
) -> str:
    """Auto-selecciona modelo segun complejidad de tarea.

    - CHAT/SIMPLE/CODE_SIMPLE: deepseek-chat (rapido, 8K output)
    - CODE_COMPLEX/DELEGATION: deepseek-reasoner (64K output, chain-of-thought)

    Solo aplica si base_model es "deepseek-chat" y auto_select es True.
    Si el usuario configuro un modelo custom, se respeta sin cambiar.

    Args:
        base_model: Modelo base del config (ej: "deepseek-chat")
        task_level: Nivel de la tarea (del clasificador)
        auto_select: Si True, auto-selecciona modelo optimo

    Returns:
        Modelo a usar para esta llamada API
    """
    if not auto_select:
        return base_model
    # Solo auto-seleccionar si el base es el default
    if base_model != MODEL_CHAT:
        return base_model
    # Tareas complejas: usar reasoner (64K output, chain-of-thought)
    if task_level.value >= TaskLevel.CODE_COMPLEX.value:
        return MODEL_REASONER
    return MODEL_CHAT


def get_max_tokens(
    task_level: TaskLevel,
    config_max: Optional[int] = None,
) -> int:
    """Retorna max_tokens de output apropiado por nivel.

    Args:
        task_level: Nivel de la tarea
        config_max: Techo opcional del config del usuario

    Returns:
        max_tokens para pasar a la API
    """
    default = MAX_TOKENS_MAP.get(task_level, 8192)
    if config_max and config_max > 0:
        # config_max es un piso, no un techo — nunca reducir los defaults adaptativos
        return max(default, config_max)
    return default


def build_api_params(
    model: str,
    messages: List[Dict],
    tools: Optional[List[Dict]],
    task_level: TaskLevel,
    config: Optional[Dict] = None,
) -> Dict:
    """Construye kwargs para chat.completions.create().

    Centraliza la logica que estaba duplicada en _chat_api
    y _chat_with_system_api de deepseek_client.py.

    Args:
        model: Modelo base (de self.model)
        messages: Lista de mensajes del historial
        tools: Herramientas OpenAI-format (o None)
        task_level: Nivel de la tarea
        config: Config completa del usuario (opcional)

    Returns:
        Dict con todos los kwargs para create()
    """
    config = config or {}
    effective_model = select_model_for_task(
        model, task_level, config.get("auto_select_model", True),
    )
    max_tokens = get_max_tokens(task_level, config.get("max_tokens"))

    params = {
        "model": effective_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"

    # Log si se auto-selecciono modelo diferente
    if effective_model != model:
        print(
            f"  [api] Auto-select: {model} -> {effective_model} "
            f"(nivel={task_level.name}, max_tokens={max_tokens})",
            file=sys.stderr,
        )

    return params
