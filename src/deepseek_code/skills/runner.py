"""Ejecutor de skills: interpreta definiciones YAML y ejecuta los pasos."""

import re
import json
from typing import Dict, Optional, Callable, Any
from ..server.protocol import MCPServer, MCPRequest, MCPMethod
from .loader import SkillDefinition, SkillStep


class SkillRunner:
    """Ejecuta un skill paso a paso usando las herramientas MCP."""

    def __init__(self, mcp_server: MCPServer, on_step: Optional[Callable] = None):
        self.mcp = mcp_server
        self.on_step = on_step

    async def run(self, skill: SkillDefinition, params: dict) -> dict:
        """Ejecuta un skill con los parametros dados.

        Args:
            skill: Definicion del skill a ejecutar
            params: Parametros proporcionados por el usuario

        Returns:
            dict con id de cada paso como key y resultado como value
        """
        # Validar parametros requeridos
        for param in skill.parameters:
            if param.required and param.name not in params:
                if param.default is not None:
                    params[param.name] = param.default
                else:
                    raise ValueError(f"Parametro requerido '{param.name}' no proporcionado")

        # Aplicar defaults
        for param in skill.parameters:
            if param.name not in params and param.default is not None:
                params[param.name] = param.default

        results = {}

        for step in skill.steps:
            # Verificar que la herramienta existe
            if step.tool not in self.mcp.tools:
                if step.optional:
                    results[step.id] = {
                        "success": False,
                        "result": None,
                        "error": f"Herramienta '{step.tool}' no encontrada"
                    }
                    await self._notify_step(step, results[step.id])
                    continue
                else:
                    raise RuntimeError(f"Herramienta '{step.tool}' no encontrada en paso '{step.id}'")

            # Resolver templates en argumentos
            resolved_args = self._resolve_templates(step.args, params, results)

            # Ejecutar la herramienta
            try:
                request = MCPRequest(
                    id=step.id,
                    method=MCPMethod.TOOLS_CALL,
                    params={"name": step.tool, "arguments": resolved_args}
                )
                response = await self.mcp.handle_request(request)

                if hasattr(response, 'error'):
                    error_msg = str(response.error.message) if hasattr(response.error, 'message') else str(response.error)
                    if step.optional:
                        results[step.id] = {"success": False, "result": None, "error": error_msg}
                    else:
                        raise RuntimeError(f"Paso '{step.id}' fallo: {error_msg}")
                else:
                    result = response.result
                    if isinstance(result, dict) and "content" in result:
                        result = result["content"]
                    results[step.id] = {"success": True, "result": result, "error": None}

            except RuntimeError:
                raise
            except Exception as e:
                if step.optional:
                    results[step.id] = {"success": False, "result": None, "error": str(e)}
                else:
                    raise RuntimeError(f"Paso '{step.id}' fallo: {e}")

            await self._notify_step(step, results[step.id])

        return results

    def resolve_output(self, skill: SkillDefinition, params: dict, results: dict) -> str:
        """Resuelve el template de output del skill."""
        if not skill.output:
            # Generar output por defecto
            lines = [f"Skill '{skill.name}' completado:"]
            for step in skill.steps:
                r = results.get(step.id, {})
                status = "OK" if r.get("success") else "FALLO"
                lines.append(f"  [{status}] {step.description or step.id}")
            return "\n".join(lines)

        return self._replace_vars(skill.output, params, results)

    def _resolve_templates(self, args: dict, params: dict, step_results: dict) -> dict:
        """Resuelve {{ variable }} en los argumentos."""
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._replace_vars(value, params, step_results)
            elif isinstance(value, bool):
                resolved[key] = value
            elif isinstance(value, (int, float)):
                resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_templates(value, params, step_results)
            elif isinstance(value, list):
                resolved[key] = [
                    self._replace_vars(v, params, step_results) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    def _replace_vars(self, text: str, params: dict, step_results: dict) -> str:
        """Reemplaza {{ var }} con valores reales."""
        def replacer(match):
            expr = match.group(1).strip()

            # Parametro directo: {{ path }}
            if expr in params:
                return str(params[expr])

            # Resultado de paso: {{ steps.scan.result }}
            if expr.startswith("steps."):
                parts = expr.split(".", 2)
                if len(parts) >= 3:
                    step_id = parts[1]
                    field = parts[2]
                    if step_id in step_results:
                        value = step_results[step_id].get(field, "")
                        return str(value) if value is not None else ""

            return match.group(0)  # Dejar sin resolver

        return re.sub(r'\{\{\s*(.+?)\s*\}\}', replacer, text)

    async def _notify_step(self, step: SkillStep, result: dict):
        """Notifica paso completado via callback."""
        if self.on_step:
            try:
                import asyncio
                ret = self.on_step(step, result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                pass
