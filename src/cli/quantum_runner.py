"""Orquestador principal del flujo QuantumBridge.

Ejecuta delegaciones paralelas duales: divide la tarea en dos angulos
complementarios, ejecuta ambos en paralelo, y fusiona las respuestas.

Uso CLI:
    python run.py --quantum "tarea" --template game.js --json
    python run.py --quantum "tarea" --quantum-angles "logica,render" --json
"""

import sys
import time

from cli.config_loader import load_config, SKILLS_DIR
from cli.bridge_utils import (
    redirect_output, restore_output, output_json, output_text,
    load_file_safe, check_credentials, handle_no_credentials,
)


def run_quantum(
    task: str,
    template_path: str = None,
    angle_names: str = None,
    json_mode: bool = False,
    config_path: str = None,
    max_retries: int = 1,
    validate: bool = True,
):
    """Flujo completo de delegacion quantum (paralela dual).

    1. Crea MCPServer compartido y dos clientes
    2. Detecta/recibe angulos complementarios
    3. Ejecuta ambos en paralelo via DualSession
    4. Fusiona respuestas con merge_engine
    5. Valida resultado; fallback secuencial si falla
    6. Output JSON o texto

    Args:
        task: Descripcion de la tarea
        template_path: Ruta al template con TODOs (opcional)
        angle_names: Nombres de angulos separados por coma (opcional)
        json_mode: Si True, stdout contiene JSON
        config_path: Ruta a config.json alternativa
        max_retries: Reintentos si merge falla
        validate: Si True, valida con delegate_validator
    """
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        _run_quantum_inner(
            task, template_path, angle_names, json_mode,
            config_path, max_retries, validate, originals,
        )
    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "quantum"})
        else:
            print(f"Error quantum: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def _run_quantum_inner(
    task, template_path, angle_names, json_mode,
    config_path, max_retries, validate, originals,
):
    """Logica interna del flujo quantum (separada para manejo de errores)."""
    import asyncio
    from cli.quantum_helpers import create_shared_mcp_server, create_client_from_config
    from deepseek_code.quantum.dual_session import DualSession
    from deepseek_code.quantum.angle_detector import (
        detect_angles, build_angle_system_prompt, build_manual_angles,
    )
    from deepseek_code.quantum.merge_engine import merge_responses
    from deepseek_code.agent.prompts import build_delegate_prompt
    from deepseek_code.client.prompt_builder import assemble_delegate_prompt

    config = load_config(config_path)
    if not check_credentials(config):
        handle_no_credentials(json_mode, originals, mode="quantum")

    # Advertir consumo doble
    print(
        "  [quantum] NOTA: Modo quantum usa 2 sesiones paralelas "
        "(2x PoW challenges, 2x chats).",
        file=sys.stderr,
    )

    # Cargar template
    template = None
    if template_path:
        template = load_file_safe(template_path, "Template quantum")

    # Crear MCPServer compartido y dos clientes
    print("  [quantum] Creando MCPServer compartido...", file=sys.stderr)
    mcp = create_shared_mcp_server(config)
    client_a = create_client_from_config(config, mcp, label="A")
    client_b = create_client_from_config(config, mcp, label="B")
    dual = DualSession(client_a, client_b)

    # Detectar o crear angulos
    if angle_names:
        parts = [p.strip() for p in angle_names.split(",")]
        if len(parts) >= 2:
            angle_a, angle_b = build_manual_angles(parts[0], parts[1])
        else:
            angle_a, angle_b = detect_angles(task, template)
    else:
        angle_a, angle_b = detect_angles(task, template)

    print(
        f"  [quantum] Angulos: A='{angle_a.label}', B='{angle_b.label}'",
        file=sys.stderr,
    )

    # System prompt modular: bloques QUANTUM incluidos, sin bloques innecesarios
    from cli.config_loader import APPDATA_DIR
    from deepseek_code.sessions.session_orchestrator import SessionOrchestrator
    from deepseek_code.client.session_chat import get_session_store
    from deepseek_code.surgical.integration import post_delegation
    from deepseek_code.global_memory.global_integration import (
        global_post_delegation, get_injected_skill_names, detect_project_name,
    )

    quantum_base = assemble_delegate_prompt(
        has_template=template is not None,
        is_quantum=True,
    )

    # SessionOrchestrator detecta inyecciones (skills, surgical, global)
    skills_dir = config.get("skills_dir", SKILLS_DIR)
    appdata_dir = config.get("_appdata_dir", APPDATA_DIR)
    task_text = task + (" " + template[:500] if template else "")

    orchestrator = SessionOrchestrator(
        get_session_store(), skills_dir=skills_dir, appdata_dir=appdata_dir,
    )
    call_params = orchestrator.prepare_session_call(
        mode="quantum", identifier=f"quantum_{angle_names or 'auto'}",
        user_message=task, base_system_prompt=quantum_base,
        task_text=task_text, template_path=template_path,
    )

    surgical_store = call_params.get("surgical_store")
    global_store = call_params.get("global_store")

    # Quantum es stateless (2 clientes paralelos): reconstruir enriched_system
    base_system = quantum_base
    for inj in (call_params.get("pending_injections") or []):
        base_system += f"\n{inj['content']}"

    sys_a = build_angle_system_prompt(base_system, angle_a, task, template)
    sys_b = build_angle_system_prompt(base_system, angle_b, task, template)

    # Construir prompts
    prompt_a = build_delegate_prompt(task, template=template)
    prompt_b = build_delegate_prompt(task, template=template)

    # Ejecutar en paralelo
    start_time = time.time()
    dual_result = asyncio.run(
        dual.parallel_chat(prompt_a, sys_a, prompt_b, sys_b)
    )

    # Merge
    if not dual_result.any_success:
        raise RuntimeError(
            f"Ambos angulos fallaron: A={dual_result.error_a}, B={dual_result.error_b}"
        )

    merge_result = merge_responses(
        dual_result.response_a,
        dual_result.response_b,
        template=template,
        angle_a_label=angle_a.label,
        angle_b_label=angle_b.label,
    )

    print(
        f"  [quantum] Merge: strategy={merge_result.strategy}, "
        f"success={merge_result.success}",
        file=sys.stderr,
    )

    # Validar merge
    final_response = merge_result.merged
    validation = None

    if validate and template:
        from cli.delegate_validator import validate_delegate_response
        validation = validate_delegate_response(final_response, template)

        if not validation["valid"] or validation["truncated"]:
            print("  [quantum] Merge no paso validacion, intentando fallback...", file=sys.stderr)

            # Fallback: secuencial con contexto de AMBAS respuestas
            combined_context = (
                f"// Respuesta del angulo A ({angle_a.label}):\n"
                f"{dual_result.response_a[:3000]}\n\n"
                f"// Respuesta del angulo B ({angle_b.label}):\n"
                f"{dual_result.response_b[:3000]}"
            )
            fallback = asyncio.run(
                dual.sequential_fallback(
                    prompt_a, base_system,
                    context_from_a=combined_context,
                )
            )
            fallback_val = validate_delegate_response(fallback, template)

            # Usar fallback si es mejor
            if fallback_val["valid"] or len(fallback) > len(final_response):
                final_response = fallback
                validation = fallback_val
                merge_result.strategy = "fallback_sequential"
                print("  [quantum] Fallback secuencial usado.", file=sys.stderr)

    total_duration = time.time() - start_time

    # SurgicalMemory: registrar resultado
    is_valid = validation["valid"] if validation else True
    post_delegation(
        surgical_store, task, "quantum", is_valid,
        final_response, validation, total_duration,
    )
    # GlobalMemory: registrar resultado cross-proyecto
    global_post_delegation(
        global_store, task, "quantum", is_valid,
        final_response, validation=validation, duration_s=total_duration,
        skills_injected=get_injected_skill_names(task),
        project_name=detect_project_name(template_path),
    )

    # Output
    if json_mode:
        if originals:
            restore_output(*originals)
        output_json({
            "success": True,
            "mode": "quantum",
            "response": final_response,
            "merge": merge_result.to_dict(),
            "dual": dual_result.to_dict(),
            "angles": {
                "a": {"name": angle_a.name, "label": angle_a.label},
                "b": {"name": angle_b.name, "label": angle_b.label},
            },
            "validation": {
                "valid": validation["valid"],
                "issues": validation["issues"],
                "stats": validation["stats"],
            } if validation else None,
            "duration_s": round(total_duration, 1),
        })
    else:
        output_text(final_response)
