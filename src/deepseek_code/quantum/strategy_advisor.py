"""Asesor de estrategia para seleccion automatica de modo de ejecucion.

Analiza la tarea y recomienda el modo optimo:
    delegate    — Tarea simple, una sola instancia
    quantum     — Tarea compleja, dos angulos complementarios
    multi       — Tarea muy compleja, N instancias con roles
    converse    — Refinamiento iterativo, dialogo multi-turno

Puede usar DeepSeek para una recomendacion inteligente (si hay client)
o fallback a heuristicas locales (sin costo de tokens).
"""

import sys
from typing import Optional, Tuple
from dataclasses import dataclass

from deepseek_code.client.task_classifier import classify_task, TaskLevel


@dataclass
class StrategyRecommendation:
    """Recomendacion de estrategia de ejecucion."""
    mode: str  # delegate, quantum, multi, converse
    reason: str
    roles_preset: Optional[str] = None  # Preset de roles para multi
    confidence: float = 0.8
    was_ai_recommended: bool = False

    def to_dict(self) -> dict:
        result = {
            "mode": self.mode,
            "reason": self.reason,
            "confidence": self.confidence,
            "ai_recommended": self.was_ai_recommended,
        }
        if self.roles_preset:
            result["roles_preset"] = self.roles_preset
        return result


def _recommend_for_large_template(
    task_lower: str,
    template_size: int,
    has_project_context: bool,
) -> StrategyRecommendation:
    """Recomendacion para templates grandes (>3000 chars).

    Los templates grandes SIEMPRE merecen multi o quantum,
    independiente de como se clasifique el texto de la tarea.
    """
    divisible_indicators = {
        "juego", "game", "fullstack", "frontend", "backend",
        "server", "client", "logica", "render", "ui",
    }
    is_divisible = any(w in task_lower for w in divisible_indicators)

    if template_size > 8000:
        return StrategyRecommendation(
            mode="multi",
            reason=(
                f"Template muy grande ({template_size} chars), "
                "multi-instancia para mejor cobertura"
            ),
            roles_preset="generate-review",
            confidence=0.75,
        )

    if is_divisible:
        return StrategyRecommendation(
            mode="quantum",
            reason="Tarea compleja divisible en angulos complementarios",
            confidence=0.8,
        )

    return StrategyRecommendation(
        mode="quantum",
        reason=f"Template grande ({template_size} chars), dual para cobertura",
        confidence=0.7,
    )


def recommend_strategy_heuristic(
    task: str,
    has_template: bool = False,
    template_size: int = 0,
    has_project_context: bool = False,
) -> StrategyRecommendation:
    """Recomendacion heuristica de estrategia (sin costo de tokens).

    Usa el clasificador de tareas + heuristicas sobre el template
    para determinar el modo optimo.

    Args:
        task: Descripcion de la tarea
        has_template: Si hay template con TODOs
        template_size: Tamano del template en chars
        has_project_context: Si hay contexto de proyecto (CLAUDE.md)

    Returns:
        StrategyRecommendation
    """
    task_level = classify_task(task)
    task_lower = task.lower()

    # --- Template grande SIEMPRE overridea clasificacion ---
    # (un template de 10K chars no es una tarea "simple")
    if has_template and template_size > 3000:
        return _recommend_for_large_template(
            task_lower, template_size, has_project_context,
        )

    # --- Chat/Simple: delegate siempre ---
    if task_level.value <= TaskLevel.SIMPLE.value:
        return StrategyRecommendation(
            mode="delegate",
            reason="Tarea simple, una instancia es suficiente",
            confidence=0.95,
        )

    # --- Code Simple: delegate ---
    if task_level == TaskLevel.CODE_SIMPLE:
        return StrategyRecommendation(
            mode="delegate",
            reason="Tarea de codigo simple",
            confidence=0.9,
        )

    # --- Code Complex sin template: converse ---
    if task_level == TaskLevel.CODE_COMPLEX and not has_template:
        return StrategyRecommendation(
            mode="converse",
            reason="Tarea compleja sin template, dialogo iterativo recomendado",
            confidence=0.7,
        )

    # --- Template mediano (<3000): delegate con review ---
    if has_template:
        return StrategyRecommendation(
            mode="delegate",
            reason="Tarea con template, delegacion con review",
            confidence=0.85,
        )

    # --- Delegation (nivel 4) sin template: quantum ---
    if task_level == TaskLevel.DELEGATION:
        return StrategyRecommendation(
            mode="quantum",
            reason="Delegacion compleja, angulos paralelos recomendados",
            confidence=0.7,
        )

    # --- Default: delegate ---
    return StrategyRecommendation(
        mode="delegate",
        reason="Modo por defecto",
        confidence=0.6,
    )


async def recommend_strategy_ai(
    client,
    task: str,
    template_info: str = "",
    project_info: str = "",
    timeout_s: float = 10.0,
) -> StrategyRecommendation:
    """Recomendacion via DeepSeek (usa tokens pero es mas inteligente).

    Envia la tarea a DeepSeek con un prompt ultra-compacto de estrategia.
    Fallback a heuristica si falla.

    Args:
        client: DeepSeekCodeClient
        task: Descripcion de la tarea
        template_info: Info del template (tamano, TODOs, etc)
        project_info: Info del proyecto
        timeout_s: Timeout para la recomendacion

    Returns:
        StrategyRecommendation
    """
    import asyncio
    from ..client.ai_protocol import (
        AIOperation, get_system_prompt,
        build_strategy_prompt, parse_strategy_response,
    )

    system = get_system_prompt(AIOperation.STRATEGY)
    prompt = build_strategy_prompt(task, template_info, project_info)

    try:
        response = await asyncio.wait_for(
            client.chat_with_system(prompt, system, max_steps=1),
            timeout=timeout_s,
        )
        mode, reason = parse_strategy_response(response)

        # Mapear modo a preset de roles si es multi
        roles_preset = None
        if mode == "multi-session":
            mode = "multi"
            roles_preset = "generate-review"

        return StrategyRecommendation(
            mode=mode,
            reason=reason or f"Recomendado por AI: {mode}",
            roles_preset=roles_preset,
            confidence=0.85,
            was_ai_recommended=True,
        )
    except (asyncio.TimeoutError, Exception) as e:
        print(
            f"  [strategy] AI timeout/error ({e}), usando heuristica",
            file=sys.stderr,
        )
        return recommend_strategy_heuristic(task)


def recommend_strategy(
    task: str,
    has_template: bool = False,
    template_size: int = 0,
    has_project_context: bool = False,
) -> StrategyRecommendation:
    """Punto de entrada principal (sincrono, sin AI).

    Para la version con AI, usar recommend_strategy_ai() directamente.

    Args:
        task: Descripcion de la tarea
        has_template: Si hay template
        template_size: Tamano del template
        has_project_context: Si hay CLAUDE.md

    Returns:
        StrategyRecommendation
    """
    return recommend_strategy_heuristic(
        task, has_template, template_size, has_project_context,
    )
