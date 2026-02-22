"""Modo programatico para DeepSeek-Code: oneshot, agent y delegate."""

import asyncio
import json
import os
import sys
import time

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR
from cli.bridge_utils import (
    redirect_output, restore_output, output_json, output_text,
    create_app, load_file_safe, check_credentials, handle_no_credentials,
)
from cli.oneshot_helpers import (
    build_token_usage, is_surgical_task, is_multi_file_task, is_complex_task,
)


def run_oneshot(query: str, json_mode: bool = False, config_path: str = None):
    """Consulta unica. Alimenta SurgicalMemory + GlobalMemory standalone."""
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        config = load_config(config_path)

        if not check_credentials(config):
            handle_no_credentials(json_mode, originals)

        app = create_app(config)

        # SurgicalMemory + GlobalMemory: inyectar y aprender (standalone)
        from deepseek_code.surgical.integration import pre_delegation, post_delegation
        from deepseek_code.global_memory.global_integration import (
            global_pre_delegation, global_post_delegation,
            get_injected_skill_names,
        )
        surgical_briefing, surgical_store = pre_delegation(APPDATA_DIR, query)
        global_briefing, global_store = global_pre_delegation(APPDATA_DIR, query)

        start_time = time.time()

        async def _run():
            return await app.client.chat(query)

        response = asyncio.run(_run())
        duration = time.time() - start_time

        # Post-delegation: registrar aprendizaje (standalone)
        post_delegation(surgical_store, query, "oneshot", True, response, None, duration)
        global_post_delegation(
            global_store, query, "oneshot", True, response,
            duration_s=duration,
            skills_injected=get_injected_skill_names(query),
        )

        if json_mode:
            restore_output(*originals)
            originals = None
            output_json({
                "success": True,
                "response": response,
                "mode": "oneshot",
                "duration_s": round(duration, 1),
            })
        else:
            output_text(response)

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e)})
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def run_agent_oneshot(goal: str, json_mode: bool = False, config_path: str = None):
    """Ejecuta el agente autonomo y retorna el resultado.

    En modo json, stdout contiene JSON con status, steps, duration.
    En modo texto, stdout contiene el resumen final.
    Alimenta SurgicalMemory + GlobalMemory incluso sin Claude.
    """
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        config = load_config(config_path)

        if not check_credentials(config):
            handle_no_credentials(json_mode, originals, mode="agent")

        app = create_app(config)

        # SurgicalMemory + GlobalMemory: inyectar y aprender (standalone)
        from deepseek_code.surgical.integration import pre_delegation, post_delegation
        from deepseek_code.global_memory.global_integration import (
            global_pre_delegation, global_post_delegation,
            get_injected_skill_names,
        )
        surgical_briefing, surgical_store = pre_delegation(APPDATA_DIR, goal)
        global_briefing, global_store = global_pre_delegation(APPDATA_DIR, goal)

        from deepseek_code.agent.engine import AgentEngine

        agent = AgentEngine(
            client=app.client,
            max_steps=config.get("agent_max_steps", 25),
            logs_dir=os.path.join(APPDATA_DIR, "agent_logs")
        )

        async def _run():
            return await agent.run(goal)

        start_time = time.time()
        result = asyncio.run(_run())
        duration = time.time() - start_time

        status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
        is_success = status_str == "completado"

        # Post-delegation: registrar aprendizaje (standalone)
        response_text = result.final_summary or ""
        post_delegation(surgical_store, goal, "agent", is_success, response_text, None, duration)
        global_post_delegation(
            global_store, goal, "agent", is_success, response_text,
            duration_s=duration,
            skills_injected=get_injected_skill_names(goal),
        )

        if json_mode:
            restore_output(*originals)
            originals = None
            output_json({
                "success": is_success,
                "status": status_str,
                "response": response_text,
                "steps": len(result.steps),
                "duration_s": round(duration, 1),
                "mode": "agent",
                "log_file": result.log_file
            })
        else:
            output_text(result.final_summary or f"Agente finalizado: {status_str}")

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "agent"})
        else:
            print(f"Error del agente: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def run_delegate_oneshot(
    task: str,
    template_path: str = None,
    context_path: str = None,
    feedback: str = None,
    json_mode: bool = False,
    config_path: str = None,
    max_retries: int = 1,
    validate: bool = True,
    project_context_path: str = None,
    negotiate_skills: bool = False,
):
    """Delegacion con validacion, retry y auto-continuacion por truncamiento."""
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        config = load_config(config_path)

        if not check_credentials(config):
            handle_no_credentials(json_mode, originals, mode="delegate")

        template = load_file_safe(template_path, "Template") if template_path else None
        context = load_file_safe(context_path, "Contexto") if context_path else None

        from deepseek_code.agent.prompts import build_delegate_prompt
        from deepseek_code.client.prompt_builder import assemble_delegate_prompt
        from deepseek_code.skills.skill_injector import build_delegate_skills_context
        from cli.delegate_validator import validate_delegate_response, estimate_template_tokens
        from cli.collaboration import (
            run_collaborative_delegation, build_project_context,
        )

        # Estimar tokens del template y advertir si es grande
        template_analysis = None
        if template:
            template_analysis = estimate_template_tokens(template)
            if template_analysis["recommended_split"]:
                print(
                    f"[WARN] Template grande: {template_analysis['todo_count']} TODOs, "
                    f"~{template_analysis['estimated_tokens']} tokens. "
                    f"Considerar dividir en 2 delegaciones.",
                    file=sys.stderr
                )

        app = create_app(config)
        start_time = time.time()

        # Detectar tipo de tarea para ensamblaje inteligente
        is_surgical = is_surgical_task(task)
        is_multi_file = is_multi_file_task(task)
        if is_surgical:
            print("  [delegate] Modo QUIRURGICO detectado: parches, no reescritura.", file=sys.stderr)
        elif is_multi_file:
            print("  [delegate] Modo MULTI-ARCHIVO detectado.", file=sys.stderr)

        # Ensamblar system prompt MODULAR (solo bloques necesarios)
        base_system = assemble_delegate_prompt(
            has_template=template is not None,
            is_quantum=False,
            is_complex=is_complex_task(task, template),
            is_surgical=is_surgical,
            is_multi_file=is_multi_file,
        )

        # Skills adaptivas (sin Core Skills ciegos)
        skills_dir = config.get("skills_dir", SKILLS_DIR)
        task_text = task + (" " + template[:500] if template else "")
        # SurgicalMemory: inyectar contexto del proyecto
        from deepseek_code.surgical.integration import pre_delegation, post_delegation
        surgical_briefing, surgical_store = pre_delegation(
            APPDATA_DIR, task,
            template_path=template_path, context_path=context_path,
            project_context_path=project_context_path,
        )
        # GlobalMemory: inyectar perfil personal cross-proyecto
        from deepseek_code.global_memory.global_integration import (
            global_pre_delegation, global_post_delegation,
            get_injected_skill_names, detect_project_name,
        )
        global_briefing, global_store = global_pre_delegation(APPDATA_DIR, task)

        # Skills: negociadas (DeepSeek elige) o heuristicas (keyword matching)
        has_errors = bool(surgical_store and surgical_store.data.get("error_log"))
        if negotiate_skills:
            from deepseek_code.skills.skill_negotiation import negotiate_or_fallback
            skills_extra, was_negotiated = asyncio.run(
                negotiate_or_fallback(
                    app.client, task_text, skills_dir,
                    task_level="delegation",
                    enable_negotiation=True,
                    has_recurring_errors=has_errors,
                )
            )
        else:
            skills_extra = build_delegate_skills_context(
                skills_dir, task_text,
                task_level="delegation", has_recurring_errors=has_errors,
            )
        enriched_system = base_system + skills_extra + surgical_briefing + global_briefing

        # Construir contexto de proyecto para briefing
        project_ctx = build_project_context(surgical_store)

        # Delegacion colaborativa (briefing + ejecucion + review)
        response, total_continuations, validation = asyncio.run(
            run_collaborative_delegation(
                app, task, enriched_system,
                template=template, context=context, feedback=feedback,
                project_context=project_ctx,
                enable_briefing=bool(project_ctx and template),
                enable_review=validate and template is not None,
                max_review_rounds=max_retries,
            )
        )

        duration = time.time() - start_time

        # Si no hubo review en collaboration, validar aqui para el reporte
        if validation is None and validate and template:
            validation = validate_delegate_response(response, template)

        # SurgicalMemory: registrar resultado para aprendizaje
        is_success = (validation["valid"] and not validation["truncated"]) if validation else True
        post_delegation(
            surgical_store, task, "delegate", is_success,
            response, validation, duration,
        )
        # GlobalMemory: registrar resultado para aprendizaje cross-proyecto
        global_post_delegation(
            global_store, task, "delegate", is_success,
            response, validation=validation, duration_s=duration,
            skills_injected=get_injected_skill_names(task_text),
            token_usage=None,
            project_name=detect_project_name(template_path, context_path),
        )

        if json_mode:
            restore_output(*originals)
            originals = None
            result = {
                "success": True,
                "response": response,
                "mode": "delegate",
                "had_template": template is not None,
                "had_context": context is not None,
                "duration_s": round(duration, 1),
            }
            if validation:
                result["validation"] = {
                    "valid": validation["valid"],
                    "truncated": validation["truncated"],
                    "issues": validation["issues"],
                    "todos_found": validation["todos_found"],
                    "todos_missing": validation["todos_missing"],
                    "stats": validation["stats"],
                }
            if total_continuations > 0:
                result["continuations"] = total_continuations
            if template_analysis:
                result["template_analysis"] = {
                    "todo_count": template_analysis["todo_count"],
                    "estimated_tokens": template_analysis["estimated_tokens"],
                    "recommended_split": template_analysis["recommended_split"],
                }
            # Token usage report para gestion estrategica del budget de 1M
            result["token_usage"] = build_token_usage(
                system_prompt=base_system,
                skills_context=skills_extra,
                surgical_briefing=surgical_briefing,
                user_prompt=task,
                template=template,
                context=context,
                response=response,
                global_briefing=global_briefing,
            )
            output_json(result)
        else:
            output_text(response)

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "delegate"})
        else:
            print(f"Error de delegacion: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


