"""Modo conversacional multi-turno para dialogo Claude <-> DeepSeek.

Permite a Claude Code mantener una conversacion iterativa con DeepSeek,
enviando multiples mensajes y recibiendo respuestas con contexto acumulado.
Implementa el concepto de 'pensamiento cuantico compartido'.

Uso CLI:
    echo '{"messages":["hola","ahora mejora X"]}' | python run.py --converse --json
    python run.py --converse "mensaje inicial" --json
    python run.py --converse-file mensajes.json --json

Formato JSON de entrada (stdin o archivo):
    {
        "system": "system prompt opcional",
        "messages": ["mensaje 1", "mensaje 2", "mensaje 3"]
    }

Cada mensaje se envia secuencialmente, manteniendo el historial completo.
DeepSeek responde a cada uno con contexto de los anteriores.
"""

import asyncio
import json
import math
import sys
import time

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR
from cli.bridge_utils import (
    redirect_output, restore_output, output_json, output_text,
    create_app, check_credentials, handle_no_credentials,
)


def _estimate_tokens(text):
    if not text:
        return 0
    return math.ceil(len(text) / 3.5)


def run_converse(
    initial_message=None,
    converse_file=None,
    json_mode=False,
    config_path=None,
    project_context_path=None,
):
    """Ejecuta conversacion multi-turno con DeepSeek.

    Envía multiples mensajes secuencialmente manteniendo historial.
    Ideal para dialogo iterativo Claude <-> DeepSeek.

    Args:
        initial_message: Primer mensaje (si se pasa como argumento CLI)
        converse_file: Ruta a archivo JSON con mensajes
        json_mode: Si True, output JSON estructurado
        config_path: Ruta a config.json
        project_context_path: Ruta a CLAUDE.md del proyecto
    """
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        _run_converse_inner(
            initial_message, converse_file, json_mode,
            config_path, project_context_path, originals,
        )
    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "converse"})
        else:
            print(f"Error converse: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def _run_converse_inner(
    initial_message, converse_file, json_mode,
    config_path, project_context_path, originals,
):
    """Logica interna del modo conversacional."""
    config = load_config(config_path)
    if not check_credentials(config):
        handle_no_credentials(json_mode, originals, mode="converse")

    # Parsear mensajes de entrada
    messages, custom_system = _parse_converse_input(
        initial_message, converse_file,
    )

    if not messages:
        raise ValueError("No se proporcionaron mensajes para la conversacion")

    # Preparar app y system prompt
    app = create_app(config)

    # Clasificar el primer mensaje para adaptar el prompt
    from deepseek_code.client.task_classifier import classify_task, TaskLevel
    from deepseek_code.client.prompt_builder import (
        build_adaptive_system_prompt, assemble_delegate_prompt,
    )

    first_msg = messages[0] if messages else ""
    task_level = classify_task(first_msg)

    # Enriquecer system prompt con memorias si hay proyecto
    system_prompt = custom_system
    if not system_prompt:
        if task_level.value >= TaskLevel.CODE_COMPLEX.value:
            system_prompt = assemble_delegate_prompt(
                has_template=False, is_quantum=False, is_complex=True,
            )
        else:
            system_prompt = build_adaptive_system_prompt(task_level, first_msg)

    # SurgicalMemory + GlobalMemory
    from deepseek_code.surgical.integration import pre_delegation, post_delegation
    from deepseek_code.global_memory.global_integration import (
        global_pre_delegation, global_post_delegation,
        get_injected_skill_names, detect_project_name,
    )
    from deepseek_code.skills.skill_injector import build_delegate_skills_context

    task_summary = " ".join(messages[:2])[:500]
    skills_dir = config.get("skills_dir", SKILLS_DIR)

    # Solo inyectar skills si el nivel lo amerita
    level_name = task_level.name.lower()
    skills_extra = ""
    if task_level.value >= TaskLevel.CODE_SIMPLE.value:
        skills_extra = build_delegate_skills_context(
            skills_dir, task_summary, task_level=level_name,
        )

    surgical_briefing, surgical_store = pre_delegation(
        APPDATA_DIR, task_summary,
        project_context_path=project_context_path,
    )
    global_briefing, global_store = global_pre_delegation(
        APPDATA_DIR, task_summary,
    )

    enriched_system = system_prompt + skills_extra + surgical_briefing + global_briefing

    # Configurar el client con el system prompt enriquecido
    app.client.system_message = enriched_system
    app.client.conversation_history = [
        {"role": "system", "content": enriched_system}
    ]

    # Ejecutar conversacion multi-turno
    start_time = time.time()
    turns = []

    for i, msg in enumerate(messages):
        turn_start = time.time()
        print(
            f"[converse] Turno {i + 1}/{len(messages)}: {msg[:80]}...",
            file=sys.stderr,
        )

        response = asyncio.run(_converse_turn(app, msg))
        turn_duration = time.time() - turn_start

        turns.append({
            "turn": i + 1,
            "user": msg,
            "assistant": response,
            "duration_s": round(turn_duration, 1),
            "response_tokens": _estimate_tokens(response),
        })

        print(
            f"[converse] Turno {i + 1} completado: "
            f"{_estimate_tokens(response)} tokens en {round(turn_duration, 1)}s",
            file=sys.stderr,
        )

    total_duration = time.time() - start_time
    last_response = turns[-1]["assistant"] if turns else ""

    # Post-delegation: registrar aprendizaje
    post_delegation(
        surgical_store, task_summary, "converse", True,
        last_response, None, total_duration,
    )
    global_post_delegation(
        global_store, task_summary, "converse", True,
        last_response, duration_s=total_duration,
        skills_injected=get_injected_skill_names(task_summary),
        project_name=detect_project_name(project_context_path),
    )

    # Output
    if json_mode:
        if originals:
            restore_output(*originals)
        total_input_tokens = sum(_estimate_tokens(t["user"]) for t in turns)
        total_output_tokens = sum(t["response_tokens"] for t in turns)
        output_json({
            "success": True,
            "mode": "converse",
            "response": last_response,
            "turns": turns,
            "total_turns": len(turns),
            "duration_s": round(total_duration, 1),
            "token_usage": {
                "system_prompt": _estimate_tokens(enriched_system),
                "total_input": total_input_tokens,
                "total_output": total_output_tokens,
                "total_estimated": (
                    _estimate_tokens(enriched_system)
                    + total_input_tokens + total_output_tokens
                ),
            },
        })
    else:
        output_text(last_response)


async def _converse_turn(app, message):
    """Ejecuta un turno de conversacion (mantiene historial).

    Limpia markdown residual de la respuesta de DeepSeek.
    """
    from cli.oneshot_helpers import strip_markdown_fences
    response = await app.client.chat(message)
    return strip_markdown_fences(response)


def _parse_converse_input(initial_message, converse_file):
    """Parsea los mensajes de entrada para la conversacion.

    Returns:
        Tupla (lista_mensajes, system_prompt_opcional)
    """
    messages = []
    custom_system = None

    # Prioridad 1: archivo JSON
    if converse_file:
        try:
            with open(converse_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                messages = data.get("messages", [])
                custom_system = data.get("system")
            elif isinstance(data, list):
                messages = data
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(f"Error leyendo archivo de conversacion: {e}")

    # Prioridad 2: stdin (si no es terminal)
    if not messages and not sys.stdin.isatty():
        try:
            stdin_data = sys.stdin.read().strip()
            if stdin_data:
                data = json.loads(stdin_data)
                if isinstance(data, dict):
                    messages = data.get("messages", [])
                    custom_system = data.get("system")
                elif isinstance(data, list):
                    messages = data
        except json.JSONDecodeError:
            # Si no es JSON, tratar como mensaje unico
            if stdin_data:
                messages = [stdin_data]

    # Prioridad 3: mensaje CLI
    if initial_message:
        messages.insert(0, initial_message)

    return messages, custom_system
