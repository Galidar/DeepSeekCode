"""Protocolo de colaboracion real Claude <-> DeepSeek.

Implementa un dialogo de 3 fases para delegaciones:
  Fase 1 — Briefing: Contextualiza a DeepSeek sobre el proyecto
  Fase 2 — Ejecucion: La delegacion propiamente dicha
  Fase 3 — Review: Claude revisa y DeepSeek corrige

El protocolo es opt-in: solo se activa para tareas que lo ameriten.
Para tareas simples se salta directamente a ejecucion.
"""

import sys
from typing import Optional, Tuple


async def run_collaborative_delegation(
    app,
    task: str,
    system_prompt: str,
    template: str = None,
    context: str = None,
    feedback: str = None,
    project_context: dict = None,
    enable_briefing: bool = True,
    enable_review: bool = True,
    max_review_rounds: int = 2,
    max_continuations: int = 3,
) -> Tuple[str, int, Optional[dict]]:
    """Delegacion colaborativa con briefing y review.

    Fase 1: Briefing (opt-in) — contextualiza a DeepSeek
    Fase 2: Ejecucion — la delegacion real
    Fase 3: Review (opt-in) — revisa y corrige iterativamente

    Args:
        app: DeepSeekCodeApp con client configurado
        task: Tarea a delegar
        system_prompt: System prompt ensamblado
        template: Template con TODOs (opcional)
        context: Codigo de referencia (opcional)
        feedback: Feedback de intento anterior (opcional)
        project_context: Dict con info del proyecto para briefing
        enable_briefing: Si True, hace briefing pre-tarea
        enable_review: Si True, revisa y pide correcciones
        max_review_rounds: Maximo de rondas de review
        max_continuations: Maximo de auto-continuaciones por truncamiento

    Returns:
        Tupla (respuesta_final, total_continuaciones, validacion)
    """
    from deepseek_code.agent.prompts import build_delegate_prompt
    from cli.oneshot_helpers import strip_markdown_fences

    # Configurar historial como conversacion multi-turno
    app.client.system_message = system_prompt
    app.client.conversation_history = [
        {"role": "system", "content": system_prompt}
    ]

    # === FASE 1: Briefing ===
    if enable_briefing and project_context:
        briefing_msg = _build_briefing_message(task, project_context)
        print("  [collab] Fase 1: Briefing pre-tarea...", file=sys.stderr)
        briefing_response = await app.client.chat(briefing_msg)
        print(
            f"  [collab] Briefing: DeepSeek confirmo ({len(briefing_response)} chars)",
            file=sys.stderr,
        )

    # === FASE 2: Ejecucion ===
    print("  [collab] Fase 2: Ejecucion...", file=sys.stderr)

    # Chunking inteligente: si el template es muy grande, dividirlo
    from deepseek_code.client.template_chunker import should_chunk, chunk_by_todos, build_chunk_prompt
    chunk_threshold = app.client.config.get("chunk_threshold_tokens", 30000) if hasattr(app.client, 'config') else 30000

    if template and should_chunk(template, chunk_threshold):
        response, continuations = await _execute_chunked(
            app, task, template, context, feedback,
            system_prompt, max_continuations, chunk_threshold,
        )
    else:
        user_prompt = build_delegate_prompt(
            task, template=template, context=context, feedback=feedback,
        )
        response, continuations = await _execute_with_continuation(
            app, user_prompt, system_prompt, max_continuations,
        )
    response = strip_markdown_fences(response)

    # === FASE 3: Review ===
    validation = None
    if enable_review and template:
        response, validation = await _review_phase(
            app, response, template, max_review_rounds,
        )

    return response, continuations, validation


async def _execute_chunked(
    app, task: str, template: str, context: str,
    feedback: str, system_prompt: str,
    max_continuations: int, chunk_threshold: int,
) -> Tuple[str, int]:
    """Ejecuta delegacion chunkeada para templates grandes.

    Divide el template en chunks logicos y ejecuta cada uno
    secuencialmente, pasando el output anterior como contexto.

    Returns:
        (respuesta_concatenada, total_continuaciones)
    """
    from deepseek_code.client.template_chunker import chunk_by_todos, build_chunk_prompt
    from deepseek_code.agent.prompts import build_delegate_prompt

    chunks = chunk_by_todos(template, max_tokens_per_chunk=chunk_threshold // 6)
    print(
        f"  [collab] Template chunkeado: {len(chunks)} chunks",
        file=sys.stderr,
    )

    all_parts = []
    total_conts = 0
    previous_output = ""

    for i, chunk in enumerate(chunks):
        chunk_prompt = build_chunk_prompt(
            chunk, len(chunks), i, task, previous_output,
        )
        user_prompt = build_delegate_prompt(
            task, template=chunk_prompt, context=context, feedback=feedback,
        )

        part, conts = await _execute_with_continuation(
            app, user_prompt, system_prompt, max_continuations,
        )
        all_parts.append(part)
        total_conts += conts
        previous_output = part

        print(
            f"  [collab] Chunk {i+1}/{len(chunks)}: {len(part)} chars",
            file=sys.stderr,
        )

    return "\n".join(all_parts), total_conts


async def _execute_with_continuation(
    app, user_prompt: str, system_prompt: str, max_continuations: int = 3,
) -> Tuple[str, int]:
    """Ejecuta delegacion con auto-continuacion por truncamiento.

    Detecta respuestas truncadas y envia 'continua' para completar.

    Returns:
        (respuesta_completa, num_continuaciones)
    """
    from cli.delegate_validator import _detect_truncation

    response = await app.client.chat_with_system(user_prompt, system_prompt)
    parts = [response]
    continuation_count = 0

    for i in range(max_continuations):
        truncation_signs = _detect_truncation(response)
        if not truncation_signs:
            break

        continuation_count += 1
        print(
            f"  [collab] Continuacion {continuation_count}/{max_continuations}: "
            f"truncado ({truncation_signs[0]})",
            file=sys.stderr,
        )

        app.client.conversation_history.append(
            {"role": "assistant", "content": response}
        )
        continue_msg = (
            "Continua EXACTAMENTE donde te quedaste. "
            "No repitas codigo anterior. Empieza desde la ultima linea."
        )
        app.client.conversation_history.append(
            {"role": "user", "content": continue_msg}
        )

        response = await app.client.chat_with_system(continue_msg, system_prompt)
        parts.append(response)

    return "\n".join(parts), continuation_count


async def _review_phase(
    app, response: str, template: str, max_rounds: int = 2,
) -> Tuple[str, Optional[dict]]:
    """Fase 3: Review iterativo.

    Claude analiza la respuesta y si hay problemas,
    los comunica a DeepSeek para que los corrija.

    Returns:
        (respuesta_final, ultimo_validation)
    """
    from cli.delegate_validator import validate_delegate_response
    from cli.oneshot_helpers import strip_markdown_fences

    validation = validate_delegate_response(response, template)

    for round_num in range(max_rounds):
        # Si es valido y no truncado, aceptar
        if validation["valid"] and not validation["truncated"]:
            if round_num > 0:
                print(
                    f"  [collab] Review round {round_num}: APROBADO",
                    file=sys.stderr,
                )
            break

        # Construir mensaje de review
        review_msg = _build_review_message(validation, round_num + 1)
        print(
            f"  [collab] Fase 3: Review round {round_num + 1} "
            f"({len(validation['issues'])} problemas)...",
            file=sys.stderr,
        )

        # Enviar review a DeepSeek (en la misma conversacion)
        app.client.conversation_history.append(
            {"role": "assistant", "content": response}
        )
        app.client.conversation_history.append(
            {"role": "user", "content": review_msg}
        )

        corrected = await app.client.chat_with_system(
            review_msg,
            app.client.system_message,
        )
        response = strip_markdown_fences(corrected)
        validation = validate_delegate_response(response, template)

    return response, validation


def _build_briefing_message(task: str, project_context: dict) -> str:
    """Construye el mensaje de briefing pre-tarea.

    Incluye instrucciones explicitas sobre el scope del trabajo
    para evitar que DeepSeek reescriba todo en vez de parchear.

    Args:
        task: Resumen de la tarea
        project_context: Dict con name, conventions, errors, structure
    """
    parts = ["BRIEFING PRE-TAREA:"]
    parts.append("Vas a recibir una tarea de codigo. Contexto del proyecto:\n")

    if project_context.get("name"):
        parts.append(f"PROYECTO: {project_context['name']}")

    if project_context.get("conventions"):
        parts.append(f"\nCONVENCIONES:\n{project_context['conventions']}")

    if project_context.get("errors"):
        parts.append(f"\nERRORES A EVITAR:\n{project_context['errors']}")

    if project_context.get("structure"):
        structure = project_context["structure"]
        if len(structure) > 800:
            structure = structure[:800] + "..."
        parts.append(f"\nESTRUCTURA:\n{structure}")

    parts.append(f"\nTAREA QUE VIENE: {task[:300]}")

    # Instrucciones de scope basadas en la leccion de Jet Combat 3D:
    # DeepSeek recibia 20 bugs y reescribia todo en vez de parchear
    parts.append(
        "\nINSTRUCCIONES DE SCOPE CRITICAS:"
        "\n- Modifica SOLO lo que la tarea pide. No toques codigo que funciona."
        "\n- Si la tarea es corregir bugs: devuelve PARCHES, no archivos completos."
        "\n- Si la tarea es generar codigo nuevo: genera SOLO lo pedido."
        "\n- NUNCA reescribas un archivo entero para arreglar 3 lineas."
        "\n- NUNCA agregues features, refactorizaciones o mejoras no solicitadas."
    )

    parts.append(
        "\nConfirma que entiendes el contexto y las restricciones de scope. "
        "Responde en 1-2 oraciones, no escribas codigo aun."
    )

    return "\n".join(parts)


def _build_review_message(validation: dict, round_num: int) -> str:
    """Construye el mensaje de review para DeepSeek.

    Args:
        validation: Resultado de validate_delegate_response
        round_num: Numero de ronda de review
    """
    parts = [f"REVISION DE TU CODIGO (ronda {round_num}):"]

    issues = validation.get("issues", [])
    if issues:
        parts.append(f"Tu respuesta tiene {len(issues)} problemas:")
        for i, issue in enumerate(issues[:8], 1):
            parts.append(f"  {i}. {issue}")

    if validation.get("truncated"):
        parts.append(
            "\nADEMAS: Tu respuesta fue TRUNCADA. "
            "Reduce el tamano de cada funcion (max 25 lineas)."
        )

    missing = validation.get("todos_missing", [])
    if missing:
        parts.append(f"\nTODOs FALTANTES: {', '.join(missing[:10])}")
        parts.append("Debes implementar TODOS los TODOs del template.")

    parts.append(
        "\nCorrige estos problemas y devuelve el codigo COMPLETO corregido. "
        "Solo codigo, sin explicaciones."
    )

    return "\n".join(parts)


def build_project_context(surgical_store) -> Optional[dict]:
    """Construye el contexto del proyecto desde SurgicalMemory.

    Args:
        surgical_store: SurgicalStore con datos del proyecto

    Returns:
        Dict con name, conventions, errors, structure o None
    """
    if not surgical_store:
        return None

    try:
        data = surgical_store.data
        context = {}

        if data.get("project_name"):
            context["name"] = data["project_name"]

        # Convenciones
        conv = data.get("conventions", {})
        if conv:
            parts = []
            if conv.get("naming"):
                parts.append(f"Naming: {conv['naming']}")
            if conv.get("patterns"):
                parts.append(f"Patrones: {conv['patterns']}")
            context["conventions"] = ". ".join(parts) if parts else ""

        # Errores frecuentes (top 5)
        errors = data.get("error_log", [])
        if errors:
            recent = errors[-5:]
            context["errors"] = "\n".join(
                f"- {e.get('summary', str(e))}" for e in recent
            )

        # Arquitectura
        arch = data.get("architecture", {})
        if arch:
            context["structure"] = str(arch)[:500]

        return context if any(context.values()) else None

    except Exception:
        return None
