"""Ejecutor de planes multi-paso para DeepSeek-Code.

Permite a Claude Code orquestar tareas complejas divididas en pasos
secuenciales, donde cada paso puede recibir el resultado de pasos
previos como contexto adicional. Soporta grupos paralelos y modo dual.

Uso:
    python run.py --multi-step plan.json --json
    python run.py --multi-step-inline '{"steps":[...]}' --json

Formato del plan JSON:
    {
        "steps": [
            {
                "id": "step_1",
                "task": "Descripcion de la tarea",
                "template": "ruta/al/template.js",
                "context_from": [],
                "max_retries": 1,
                "validate": true,
                "parallel_group": "grupo_1",
                "dual_mode": false
            }
        ]
    }
"""

import asyncio
import json
import sys
import time
from typing import Dict, List

from cli.config_loader import load_config, SKILLS_DIR
from cli.bridge_utils import (
    redirect_output, restore_output, output_json, output_text,
    create_app, load_file_safe, check_credentials, handle_no_credentials,
)
from cli.multi_step_helpers import (
    execute_step_dual, execute_parallel_group, group_steps, log_step_result,
)


class StepSpec:
    """Especificacion de un paso del plan."""

    def __init__(self, data: dict):
        self.id = data.get("id", f"step_{id(data)}")
        self.task = data.get("task", "")
        self.template_path = data.get("template")
        self.context_from = data.get("context_from", [])
        self.max_retries = data.get("max_retries", 1)
        self.validate = data.get("validate", True)
        self.feedback = data.get("feedback")
        self.parallel_group = data.get("parallel_group")
        self.dual_mode = data.get("dual_mode", False)

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "task": self.task,
            "template": self.template_path,
            "context_from": self.context_from,
            "max_retries": self.max_retries,
            "validate": self.validate,
        }
        if self.parallel_group:
            result["parallel_group"] = self.parallel_group
        if self.dual_mode:
            result["dual_mode"] = True
        return result


class StepResult:
    """Resultado de un paso ejecutado."""

    def __init__(self, step_id: str):
        self.step_id = step_id
        self.success = False
        self.response = ""
        self.duration_s = 0.0
        self.validation = None
        self.error = None

    def to_dict(self) -> dict:
        result = {
            "step_id": self.step_id,
            "success": self.success,
            "duration_s": round(self.duration_s, 1),
        }
        if self.success:
            result["response"] = self.response
        if self.validation:
            result["validation"] = self.validation
        if self.error:
            result["error"] = self.error
        return result


def _parse_plan(plan_path: str = None, plan_inline: str = None) -> List[StepSpec]:
    """Parsea el plan desde archivo o JSON inline."""
    if plan_path:
        raw = load_file_safe(plan_path, "Plan multi-paso")
        data = json.loads(raw)
    elif plan_inline:
        data = json.loads(plan_inline)
    else:
        raise ValueError("Se requiere --multi-step o --multi-step-inline")

    steps_data = data.get("steps", [])
    if not steps_data:
        raise ValueError("El plan no contiene pasos (steps)")

    return [StepSpec(s) for s in steps_data]


def _build_context_from_results(
    context_from: List[str],
    completed: Dict[str, StepResult],
) -> str:
    """Construye contexto a partir de resultados de pasos previos."""
    if not context_from:
        return ""

    parts = []
    for step_id in context_from:
        prev = completed.get(step_id)
        if not prev or not prev.success:
            continue
        response = prev.response
        if len(response) > 4000:
            response = response[:4000] + "\n\n[... respuesta truncada ...]"
        parts.append(f"\n--- Resultado de '{step_id}' ---\n{response}\n")

    if not parts:
        return ""
    return "\n== CONTEXTO DE PASOS PREVIOS ==\n" + "".join(parts) + "\n== FIN CONTEXTO ==\n"


async def _execute_step(
    app, step: StepSpec, completed: Dict[str, StepResult], config: dict,
) -> StepResult:
    """Ejecuta un paso individual del plan (async).

    Si el paso tiene dual_mode=True, usa DualSession para ejecucion paralela.
    """
    result = StepResult(step.id)
    start_time = time.time()

    try:
        from deepseek_code.agent.prompts import DELEGATE_SYSTEM_PROMPT, build_delegate_prompt
        from deepseek_code.skills.skill_injector import build_delegate_skills_context

        template = None
        if step.template_path:
            template = load_file_safe(step.template_path, f"Template ({step.id})")

        prev_context = _build_context_from_results(step.context_from, completed)
        skills_dir = config.get("skills_dir", SKILLS_DIR)
        skills_extra = build_delegate_skills_context(
            skills_dir, step.task + (" " + template[:500] if template else "")
        )
        # SurgicalMemory: inyectar contexto del proyecto
        from deepseek_code.surgical.integration import pre_delegation, post_delegation
        surgical_briefing, surgical_store = pre_delegation(
            config.get("_appdata_dir", ""), step.task,
            template_path=step.template_path,
        )
        # GlobalMemory: inyectar perfil personal cross-proyecto
        from deepseek_code.global_memory.global_integration import (
            global_pre_delegation, global_post_delegation,
            get_injected_skill_names, detect_project_name,
        )
        global_briefing, global_store = global_pre_delegation(
            config.get("_appdata_dir", ""), step.task,
        )
        enriched_system = DELEGATE_SYSTEM_PROMPT + skills_extra + surgical_briefing + global_briefing

        if prev_context:
            enriched_system += prev_context

        current_feedback = step.feedback

        for attempt in range(1 + step.max_retries):
            user_prompt = build_delegate_prompt(
                step.task, template=template,
                context=None, feedback=current_feedback
            )

            if step.dual_mode:
                response = await execute_step_dual(
                    config, app.mcp_server, user_prompt, enriched_system,
                    step.task, template,
                )
            else:
                response = await app.client.chat_with_system(
                    user_prompt, enriched_system,
                )

            if step.validate and template:
                from cli.delegate_validator import validate_delegate_response
                validation = validate_delegate_response(response, template)
                result.validation = {
                    "valid": validation["valid"],
                    "truncated": validation["truncated"],
                    "issues": validation["issues"],
                    "stats": validation["stats"],
                }
                if validation["valid"] and not validation["truncated"]:
                    break
                if attempt < step.max_retries and validation["feedback"]:
                    current_feedback = validation["feedback"]
                    print(
                        f"  [{step.id}] Retry {attempt + 1}: "
                        f"{'; '.join(validation['issues'][:2])}",
                        file=sys.stderr,
                    )
                    continue
            break

        result.success = True
        result.response = response

        # SurgicalMemory: registrar resultado
        step_valid = result.validation.get("valid", True) if result.validation else True
        step_trunc = result.validation.get("truncated", False) if result.validation else False
        post_delegation(
            surgical_store, step.task, "multi_step",
            step_valid and not step_trunc,
            response, result.validation, time.time() - start_time,
        )
        # GlobalMemory: registrar resultado cross-proyecto
        global_post_delegation(
            global_store, step.task, "multi_step",
            step_valid and not step_trunc,
            response, validation=result.validation,
            duration_s=time.time() - start_time,
            skills_injected=get_injected_skill_names(step.task),
            project_name=detect_project_name(step.template_path),
        )

    except Exception as e:
        result.error = str(e)
        result.success = False

    result.duration_s = time.time() - start_time
    return result


def run_multi_step(
    plan_path: str = None, plan_inline: str = None,
    json_mode: bool = False, config_path: str = None,
):
    """Ejecuta un plan multi-paso con soporte para grupos paralelos."""
    originals = None
    if json_mode:
        originals = redirect_output()

    try:
        config = load_config(config_path)
        if not check_credentials(config):
            handle_no_credentials(json_mode, originals, mode="multi_step")

        steps = _parse_plan(plan_path, plan_inline)
        app = create_app(config)

        start_time = time.time()
        completed: Dict[str, StepResult] = {}
        step_results = []
        all_success = True

        groups = group_steps(steps)

        for group in groups:
            if len(group) == 1:
                step = group[0]
                print(f"  [paso] {step.id}: {step.task[:80]}...", file=sys.stderr)
                result = asyncio.run(_execute_step(app, step, completed, config))
                completed[step.id] = result
                step_results.append(result.to_dict())
                log_step_result(result)
                if not result.success:
                    all_success = False
            else:
                group_ids = [s.id for s in group]
                print(f"  [grupo paralelo] {', '.join(group_ids)}", file=sys.stderr)
                results = asyncio.run(
                    execute_parallel_group(app, group, completed, config, _execute_step)
                )
                for result in results:
                    completed[result.step_id] = result
                    step_results.append(result.to_dict())
                    log_step_result(result)
                    if not result.success:
                        all_success = False

        total_duration = time.time() - start_time

        if json_mode:
            restore_output(*originals)
            originals = None
            output_json({
                "success": all_success, "mode": "multi_step",
                "total_steps": len(steps),
                "completed_steps": sum(1 for r in step_results if r["success"]),
                "duration_s": round(total_duration, 1), "steps": step_results,
            })
        else:
            lines = [f"Plan multi-paso: {len(steps)} pasos"]
            for r in step_results:
                status = "OK" if r["success"] else "FALLO"
                lines.append(f"  {r['step_id']}: {status} ({r['duration_s']}s)")
                if r.get("error"):
                    lines.append(f"    Error: {r['error']}")
            lines.append(f"Total: {round(total_duration, 1)}s")
            output_text("\n".join(lines))

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "multi_step"})
        else:
            print(f"Error multi-paso: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)
