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
    build_token_usage, is_surgical_task, is_multi_file_task,
)


class _TeeStderr:
    """Duplica stderr a un archivo de log para monitoreo en tiempo real.

    Todas las llamadas print(..., file=sys.stderr) van a AMBOS:
    stderr original (para CLI) y archivo de log (para monitoreo externo).
    """

    def __init__(self, original, log_path: str):
        self.original = original
        self.log = open(log_path, 'w', encoding='utf-8')

    def write(self, data):
        self.original.write(data)
        self.log.write(data)
        self.log.flush()

    def flush(self):
        self.original.flush()
        self.log.flush()

    def fileno(self):
        return self.original.fileno()

    def reconfigure(self, **kwargs):
        if hasattr(self.original, 'reconfigure'):
            self.original.reconfigure(**kwargs)

    def close_log(self):
        """Cierra el archivo de log y restaura stderr."""
        try:
            self.log.close()
        except Exception:
            pass


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
        app.client.default_session_name = "oneshot"

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
    # --- Real-time log: duplicar stderr a agent_debug.log ---
    let_log_path = os.path.join(os.getcwd(), "agent_debug.log")
    let_tee = _TeeStderr(sys.stderr, let_log_path)
    sys.stderr = let_tee
    print(f"[agent] Log en tiempo real: {let_log_path}", file=sys.stderr)

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
            max_steps=config.get("agent_max_steps", 50),
            logs_dir=os.path.join(APPDATA_DIR, "agent_logs")
        )

        async def _run():
            # --- Serena auto-init: activar code intelligence en agent mode ---
            if app.serena_manager:
                try:
                    let_serena_ok, let_serena_msg = await app.serena_manager.start()
                    if let_serena_ok:
                        print(f"  [agent] Serena activada: {let_serena_msg}", file=sys.stderr)
                    else:
                        print(f"  [agent] Serena no disponible: {let_serena_msg}", file=sys.stderr)
                except Exception as e:
                    print(f"  [agent] Serena init fallido (no critico): {e}", file=sys.stderr)
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
        # Restaurar stderr original
        if isinstance(sys.stderr, _TeeStderr):
            let_tee_ref = sys.stderr
            sys.stderr = let_tee_ref.original
            let_tee_ref.close_log()


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
    session_name: str = None,
    transfer_from: str = None,
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
        from cli.delegate_validator import validate_delegate_response, estimate_template_tokens

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
            is_surgical=is_surgical,
            is_multi_file=is_multi_file,
        )

        # --- v2.6: Orchestrator-based token-efficient injection ---
        # Skills, surgical memory, global memory are now injected as separate
        # Phase 2 messages (tracked per-session), not embedded in system prompt.
        from deepseek_code.sessions.session_orchestrator import SessionOrchestrator
        from deepseek_code.sessions.session_namespace import slugify
        from deepseek_code.client.session_chat import get_session_store
        from deepseek_code.surgical.integration import post_delegation
        from deepseek_code.global_memory.global_integration import (
            global_post_delegation, get_injected_skill_names, detect_project_name,
        )

        skills_dir = config.get("skills_dir", SKILLS_DIR)
        task_text = task + (" " + template[:5000] if template else "")

        orchestrator = SessionOrchestrator(
            get_session_store(), skills_dir=skills_dir, appdata_dir=APPDATA_DIR,
        )

        # Sesiones por defecto: continuidad automatica entre invocaciones CLI
        session_id = session_name or "default"

        call_params = orchestrator.prepare_session_call(
            mode="delegate",
            identifier=session_id,
            user_message=task,  # placeholder, real message built below
            base_system_prompt=base_system,
            task_text=task_text,
            template_path=template_path,
            context_path=context_path,
            project_context_path=project_context_path,
        )

        # Knowledge transfer: inject knowledge from another session
        if transfer_from:
            from deepseek_code.sessions.knowledge_transfer import transfer_knowledge
            actual_session = call_params["session_name"]
            kt_injection = transfer_knowledge(
                get_session_store(), transfer_from, actual_session,
            )
            if kt_injection:
                call_params["pending_injections"].append(kt_injection)
                print(
                    f"  [delegate] Conocimiento transferido desde '{transfer_from}'",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  [delegate] WARN: No se encontro sesion '{transfer_from}' para transferir",
                    file=sys.stderr,
                )

        # Extract stores for post-delegation learning
        surgical_store = call_params.get("surgical_store")
        global_store = call_params.get("global_store")

        total_continuations = 0
        validation = None

        # === MODO SESION: chat con continuidad persistente ===
        user_prompt = build_delegate_prompt(
            task, template=template, context=context, feedback=feedback,
        )
        actual_session = call_params["session_name"]
        print(f"  [delegate] Sesion '{actual_session}' "
              f"(inyecciones: {len(call_params['pending_injections'])})", file=sys.stderr)

        response = asyncio.run(
            app.client.chat_in_session(
                actual_session, user_prompt,
                call_params["system_prompt"],  # None if already sent
                pending_injections=call_params["pending_injections"],
            )
        )
        from cli.oneshot_helpers import strip_markdown_fences
        response = strip_markdown_fences(response)

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

        # Intelligence: Shadow learning (aprender de correcciones del usuario)
        if is_success and template_path:
            try:
                from deepseek_code.intelligence.integration import on_post_commit
                from deepseek_code.surgical.collector import detect_project_root
                proj_root = detect_project_root(template_path)
                if proj_root:
                    on_post_commit(APPDATA_DIR, proj_root, response, surgical_store)
            except Exception:
                pass  # fail-safe

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
            # Token usage report — estimate Phase 2 injection tokens
            let_skills_chars = 0
            let_surgical_chars = 0
            let_global_chars = 0
            for inj in call_params.get("pending_injections", []):
                let_inj_type = inj.get("type", "") if isinstance(inj, dict) else ""
                let_inj_content = inj.get("content", "") if isinstance(inj, dict) else str(inj)
                if let_inj_type.startswith("skill"):
                    let_skills_chars += len(let_inj_content)
                elif let_inj_type in ("surgical", "memory"):
                    let_surgical_chars += len(let_inj_content)
                elif let_inj_type in ("global", "knowledge"):
                    let_global_chars += len(let_inj_content)
                else:
                    let_skills_chars += len(let_inj_content)  # default bucket

            result["token_usage"] = build_token_usage(
                system_prompt=base_system,
                skills_context="x" * let_skills_chars,  # Phase 2 estimated
                surgical_briefing="x" * let_surgical_chars,  # Phase 2 estimated
                user_prompt=task,
                template=template,
                context=context,
                response=response,
                global_briefing="x" * let_global_chars,  # Phase 2 estimated
            )
            result["session_injections"] = len(call_params["pending_injections"])
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


