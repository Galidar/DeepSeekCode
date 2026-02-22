"""CLI runner para modo multi-sesion con N instancias de DeepSeek.

Ejecuta N clientes DeepSeek en paralelo con roles diferenciados.
Soporta modos: parallel (todas a la vez) y pipeline (secuencial).

Uso CLI:
    python run.py --multi "tarea" --template game.js --json
    python run.py --multi "tarea" --roles "generate-review" --json
    python run.py --multi "tarea" --roles "full-pipeline" --json
    python run.py --multi "tarea" --instances 3 --json
"""

import asyncio
import os
import sys
import time

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR
from cli.bridge_utils import (
    redirect_output, restore_output, output_json, output_text,
    load_file_safe, check_credentials, handle_no_credentials,
)


def run_multi(
    task: str,
    template_path: str = None,
    roles_preset: str = "generate-review",
    num_instances: int = 0,
    pipeline_mode: bool = False,
    json_mode: bool = False,
    config_path: str = None,
    validate: bool = True,
):
    """Flujo completo de multi-sesion.

    Args:
        task: Descripcion de la tarea
        template_path: Ruta al template (opcional)
        roles_preset: Preset de roles (generate-review, full-pipeline, etc)
        num_instances: Numero de instancias (0 = auto segun preset)
        pipeline_mode: Si True, ejecuta secuencialmente (gen -> review -> fix)
        json_mode: Si True, stdout contiene JSON
        config_path: Ruta a config.json
        validate: Si True, valida resultado con template
    """
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        _run_multi_inner(
            task, template_path, roles_preset, num_instances,
            pipeline_mode, json_mode, config_path, validate, originals,
        )
    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "multi"})
        else:
            print(f"Error multi: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def _run_multi_inner(
    task, template_path, roles_preset, num_instances,
    pipeline_mode, json_mode, config_path, validate, originals,
):
    """Logica interna del flujo multi-sesion."""
    from cli.quantum_helpers import create_shared_mcp_server, create_client_from_config
    from deepseek_code.quantum.multi_session import MultiSession
    from deepseek_code.quantum.roles import get_preset, RoleType
    from deepseek_code.client.prompt_builder import assemble_delegate_prompt
    from deepseek_code.agent.prompts import build_delegate_prompt

    config = load_config(config_path)
    if not check_credentials(config):
        handle_no_credentials(json_mode, originals, mode="multi")

    # Advertir consumo N-uple
    roles = get_preset(roles_preset)
    n = num_instances if num_instances > 0 else len(roles)

    # Si se piden mas instancias que roles, duplicar generadores
    while len(roles) < n:
        from deepseek_code.quantum.roles import build_role
        extra_label = f"gen-{len(roles)}"
        roles.append(build_role(RoleType.GENERATOR, extra_label))

    print(
        f"  [multi] Modo multi-sesion: {n} instancias, "
        f"preset={roles_preset}, "
        f"pipeline={'si' if pipeline_mode else 'no'}",
        file=sys.stderr,
    )
    print(
        f"  [multi] NOTA: Usa {n} sesiones paralelas "
        f"({n}x PoW challenges, {n}x chats).",
        file=sys.stderr,
    )

    # Cargar template
    template = None
    if template_path:
        template = load_file_safe(template_path, "Template multi")

    # Crear MCPServer compartido y N clientes
    mcp = create_shared_mcp_server(config)
    instances = []
    for i, role in enumerate(roles[:n]):
        client = create_client_from_config(config, mcp, label=role.label)
        instances.append((client, role))

    session = MultiSession(instances)

    # System prompt modular
    base_system = assemble_delegate_prompt(
        has_template=template is not None,
        is_quantum=False,
    )

    # SessionOrchestrator detecta inyecciones (skills, surgical, global)
    from deepseek_code.sessions.session_orchestrator import SessionOrchestrator
    from deepseek_code.client.session_chat import get_session_store
    from deepseek_code.surgical.integration import post_delegation
    from deepseek_code.global_memory.global_integration import (
        global_post_delegation, get_injected_skill_names, detect_project_name,
    )

    skills_dir = config.get("skills_dir", SKILLS_DIR)
    appdata_dir = config.get("_appdata_dir", APPDATA_DIR)
    task_text = task + (" " + template[:500] if template else "")

    orchestrator = SessionOrchestrator(
        get_session_store(), skills_dir=skills_dir, appdata_dir=appdata_dir,
    )
    call_params = orchestrator.prepare_session_call(
        mode="multi-step", identifier=f"multi_{roles_preset}",
        user_message=task, base_system_prompt=base_system,
        task_text=task_text, template_path=template_path,
    )

    surgical_store = call_params.get("surgical_store")
    global_store = call_params.get("global_store")

    # Multi es stateless (N clientes paralelos): reconstruir enriched_system
    enriched_system = base_system
    for inj in (call_params.get("pending_injections") or []):
        enriched_system += f"\n{inj['content']}"

    # Construir prompt de tarea
    task_prompt = build_delegate_prompt(task, template=template)

    # Ejecutar
    start_time = time.time()

    if pipeline_mode:
        multi_result = asyncio.run(
            session.sequential_pipeline(task_prompt, enriched_system)
        )
    else:
        multi_result = asyncio.run(
            session.parallel_execute(task_prompt, enriched_system)
        )

    total_duration = time.time() - start_time

    # Determinar respuesta final (del generador o del ultimo en pipeline)
    final_response = ""
    for r in multi_result.successful_results:
        if r.role_type == "generator" or not final_response:
            final_response = r.response

    # Si pipeline y hay reviewer, reportar issues
    reviewer_issues = ""
    reviewer_result = multi_result.get_by_role("reviewer")
    if reviewer_result and reviewer_result.success:
        reviewer_issues = reviewer_result.response

    # Validar
    validation = None
    if validate and template:
        from cli.delegate_validator import validate_delegate_response
        validation = validate_delegate_response(final_response, template)

    # Registrar en memorias
    is_valid = validation["valid"] if validation else multi_result.any_success
    post_delegation(
        surgical_store, task, "multi", is_valid,
        final_response, validation, total_duration,
    )
    global_post_delegation(
        global_store, task, "multi", is_valid,
        final_response, validation=validation, duration_s=total_duration,
        skills_injected=get_injected_skill_names(task),
        project_name=detect_project_name(template_path),
    )

    # Output
    if json_mode:
        if originals:
            restore_output(*originals)
        result = {
            "success": True,
            "mode": "multi",
            "response": final_response,
            "multi": multi_result.to_dict(),
            "preset": roles_preset,
            "pipeline": pipeline_mode,
            "duration_s": round(total_duration, 1),
        }
        if reviewer_issues:
            result["review"] = reviewer_issues[:2000]
        if validation:
            result["validation"] = {
                "valid": validation["valid"],
                "issues": validation["issues"],
                "stats": validation["stats"],
            }
        output_json(result)
    else:
        output_text(final_response)
