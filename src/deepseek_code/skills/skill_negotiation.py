"""Protocolo de negociacion de skills en 2 fases.

Fase 1 (Catalogo): Se envia a DeepSeek el catalogo compacto de skills
    disponibles (~2K tokens) junto con la tarea. DeepSeek responde con
    los nombres de las skills que necesita.

Fase 2 (Carga): Solo se cargan las skills solicitadas, respetando el
    budget de tokens del nivel de tarea.

Fallback: Si DeepSeek no responde o la negociacion falla, se usa el
    sistema heuristico actual (keyword matching).

Este protocolo reemplaza la inyeccion ciega de skills, dando a DeepSeek
la oportunidad de decidir que conocimiento necesita realmente.
"""

import asyncio
import sys
from typing import List, Optional, Tuple

from .skill_catalog import generate_catalog_text, load_requested_skills
from .skill_injector import build_delegate_skills_context, build_skills_context
from .skill_constants import ADAPTIVE_BUDGETS


async def negotiate_skills(
    client,
    task: str,
    skills_dir: str,
    task_level: str = "delegation",
    timeout_s: float = 15.0,
) -> Tuple[str, List[str], bool]:
    """Ejecuta el protocolo de negociacion de skills con DeepSeek.

    Envia catalogo -> DeepSeek elige -> carga solo lo pedido.
    Si falla, retorna fallback heuristico transparentemente.

    Args:
        client: DeepSeekCodeClient (para enviar el catalogo)
        task: Descripcion de la tarea
        skills_dir: Directorio de skills
        task_level: Nivel de tarea para budget
        timeout_s: Timeout para la negociacion

    Returns:
        Tupla (skills_context, nombres_cargados, fue_negociado)
        fue_negociado=True si DeepSeek eligio, False si fue fallback
    """
    budget = ADAPTIVE_BUDGETS.get(task_level, ADAPTIVE_BUDGETS["delegation"])
    if budget["total"] == 0:
        return "", [], False

    # Generar catalogo compacto
    catalog = generate_catalog_text(skills_dir)
    if not catalog:
        return "", [], False

    # Fase 1: Enviar catalogo a DeepSeek para negociacion
    from ..client.ai_protocol import (
        AIOperation, get_system_prompt,
        build_negotiate_prompt, parse_skill_response,
    )

    system = get_system_prompt(AIOperation.SKILL_NEGOTIATE)
    prompt = build_negotiate_prompt(task, catalog)

    try:
        response = await asyncio.wait_for(
            client.chat_with_system(prompt, system, max_steps=1),
            timeout=timeout_s,
        )
        requested = parse_skill_response(response)
    except (asyncio.TimeoutError, Exception) as e:
        print(
            f"  [negotiate] Timeout/error en negociacion ({e}), "
            f"usando fallback heuristico",
            file=sys.stderr,
        )
        return _fallback_heuristic(task, skills_dir, task_level), [], False

    if not requested:
        print("  [negotiate] DeepSeek no pidio skills", file=sys.stderr)
        return "", [], True

    # Fase 2: Cargar solo las skills solicitadas
    context, tokens_used, loaded = load_requested_skills(
        skills_dir, requested, token_budget=budget["total"],
    )

    print(
        f"  [negotiate] DeepSeek pidio {len(requested)} skills, "
        f"cargadas {len(loaded)}: {', '.join(loaded)} "
        f"({tokens_used} tokens)",
        file=sys.stderr,
    )

    return context, loaded, True


def negotiate_skills_sync(
    client,
    task: str,
    skills_dir: str,
    task_level: str = "delegation",
    timeout_s: float = 15.0,
) -> Tuple[str, List[str], bool]:
    """Version sincrona de negotiate_skills (para runners que usan asyncio.run).

    Args:
        Mismos que negotiate_skills

    Returns:
        Mismos que negotiate_skills
    """
    return asyncio.run(
        negotiate_skills(client, task, skills_dir, task_level, timeout_s)
    )


def _fallback_heuristic(
    task: str,
    skills_dir: str,
    task_level: str,
) -> str:
    """Fallback al sistema heuristico actual si la negociacion falla.

    Args:
        task: Descripcion de la tarea
        skills_dir: Directorio de skills
        task_level: Nivel de tarea

    Returns:
        Contexto de skills generado por keyword matching
    """
    if task_level == "delegation":
        return build_delegate_skills_context(
            skills_dir, task, task_level=task_level,
        )
    return build_skills_context(
        skills_dir, task, task_level=task_level,
    )


async def negotiate_or_fallback(
    client,
    task: str,
    skills_dir: str,
    task_level: str = "delegation",
    enable_negotiation: bool = True,
    has_recurring_errors: bool = False,
    timeout_s: float = 15.0,
) -> Tuple[str, bool]:
    """Intenta negociacion; si falla o esta deshabilitada, usa heuristica.

    Punto de entrada principal para los runners. Abstrae completamente
    la decision negotiate-vs-fallback.

    Args:
        client: DeepSeekCodeClient
        task: Descripcion de la tarea
        skills_dir: Directorio de skills
        task_level: Nivel de tarea
        enable_negotiation: Si False, usa heuristica directamente
        has_recurring_errors: Si True, inyecta error-reference
        timeout_s: Timeout para negociacion

    Returns:
        Tupla (skills_context, fue_negociado)
    """
    if not enable_negotiation or not skills_dir:
        # Fallback directo
        ctx = _fallback_with_errors(
            task, skills_dir, task_level, has_recurring_errors,
        )
        return ctx, False

    context, loaded, negotiated = await negotiate_skills(
        client, task, skills_dir, task_level, timeout_s,
    )

    if negotiated and context:
        # Negociacion exitosa — agregar error-reference si necesario
        if has_recurring_errors:
            from .skill_catalog import load_requested_skills
            err_ctx, _, _ = load_requested_skills(
                skills_dir, ["common-errors-reference"], 5000,
            )
            if err_ctx:
                context = err_ctx + "\n" + context
        return context, True

    # Fallback heuristico
    ctx = _fallback_with_errors(
        task, skills_dir, task_level, has_recurring_errors,
    )
    return ctx, False


def _fallback_with_errors(
    task: str,
    skills_dir: str,
    task_level: str,
    has_recurring_errors: bool,
) -> str:
    """Fallback heuristico con soporte para error-reference."""
    if task_level == "delegation":
        return build_delegate_skills_context(
            skills_dir, task,
            task_level=task_level,
            has_recurring_errors=has_recurring_errors,
        )
    return build_skills_context(
        skills_dir, task, task_level=task_level,
    )
