"""Helpers para ejecucion multi-paso: dual, paralelo y agrupacion.

Extraido de multi_step.py para respetar el limite de 400 lineas.
"""

import asyncio
import sys
from typing import Dict, List


async def execute_step_dual(
    config, mcp_server, user_prompt, enriched_system, task, template,
) -> str:
    """Ejecuta un paso usando DualSession (quantum inline).

    Args:
        config: Configuracion global
        mcp_server: MCPServer compartido de la app
        user_prompt: Prompt construido
        enriched_system: System prompt enriquecido
        task: Tarea original (para deteccion de angulos)
        template: Template (para deteccion de angulos)

    Returns:
        Respuesta fusionada
    """
    from cli.quantum_helpers import create_client_from_config
    from deepseek_code.quantum.dual_session import DualSession
    from deepseek_code.quantum.angle_detector import detect_angles, build_angle_system_prompt
    from deepseek_code.quantum.merge_engine import merge_responses

    client_a = create_client_from_config(config, mcp_server, label="A")
    client_b = create_client_from_config(config, mcp_server, label="B")
    dual = DualSession(client_a, client_b)

    angle_a, angle_b = detect_angles(task, template)
    sys_a = build_angle_system_prompt(enriched_system, angle_a, task, template)
    sys_b = build_angle_system_prompt(enriched_system, angle_b, task, template)

    dual_result = await dual.parallel_chat(user_prompt, sys_a, user_prompt, sys_b)

    merge_result = merge_responses(
        dual_result.response_a, dual_result.response_b, template=template,
    )
    return merge_result.merged


async def execute_parallel_group(
    app,
    group_steps,
    completed,
    config: dict,
    execute_step_fn,
) -> list:
    """Ejecuta un grupo de pasos en paralelo via asyncio.gather().

    Args:
        app: Instancia de DeepSeekCodeApp
        group_steps: Lista de StepSpec a ejecutar en paralelo
        completed: Dict de resultados previos
        config: Configuracion global
        execute_step_fn: Funcion async para ejecutar un paso

    Returns:
        Lista de StepResult
    """
    tasks = [
        execute_step_fn(app, step, completed, config)
        for step in group_steps
    ]
    return await asyncio.gather(*tasks)


def group_steps(steps) -> List[list]:
    """Agrupa pasos por parallel_group para ejecucion paralela.

    Pasos sin parallel_group se ejecutan individualmente.
    Pasos con el mismo parallel_group se agrupan juntos.
    El orden de los grupos respeta el orden de primera aparicion.
    """
    groups = []
    current_group_name = None
    current_group = []

    for step in steps:
        if step.parallel_group:
            if step.parallel_group == current_group_name:
                current_group.append(step)
            else:
                if current_group:
                    groups.append(current_group)
                current_group_name = step.parallel_group
                current_group = [step]
        else:
            if current_group:
                groups.append(current_group)
                current_group = []
                current_group_name = None
            groups.append([step])

    if current_group:
        groups.append(current_group)

    return groups


def log_step_result(result):
    """Imprime el resultado de un paso en stderr."""
    status = "OK" if result.success else "FALLO"
    print(
        f"  [{result.step_id}] {status} ({result.duration_s:.1f}s)",
        file=sys.stderr,
    )
