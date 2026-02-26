"""Sesion dual para ejecucion paralela de dos clientes DeepSeek.

Crea dos instancias independientes de DeepSeekCodeClient que comparten
un MCPServer pero tienen sesiones web/API propias. Permite ejecutar
dos chat_with_system() en paralelo via asyncio.gather().
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from deepseek_code.client.deepseek_client import DeepSeekCodeClient
from deepseek_code.server.protocol import MCPServer


@dataclass
class DualResult:
    """Resultado de una ejecucion dual."""
    response_a: str
    response_b: str
    duration_a: float
    duration_b: float
    total_duration: float
    error_a: Optional[str] = None
    error_b: Optional[str] = None

    @property
    def both_success(self) -> bool:
        return self.error_a is None and self.error_b is None

    @property
    def any_success(self) -> bool:
        return self.error_a is None or self.error_b is None

    def to_dict(self) -> dict:
        result = {
            "both_success": self.both_success,
            "total_duration_s": round(self.total_duration, 1),
            "angle_a": {
                "duration_s": round(self.duration_a, 1),
                "chars": len(self.response_a),
            },
            "angle_b": {
                "duration_s": round(self.duration_b, 1),
                "chars": len(self.response_b),
            },
        }
        if self.error_a:
            result["angle_a"]["error"] = self.error_a
        if self.error_b:
            result["angle_b"]["error"] = self.error_b
        return result


class DualSession:
    """Gestiona dos clientes DeepSeek independientes para ejecucion paralela.

    Ambos clientes comparten el mismo MCPServer (seguro para lecturas
    concurrentes via asyncio) pero tienen sesiones web/API propias.
    """

    def __init__(self, client_a: DeepSeekCodeClient, client_b: DeepSeekCodeClient):
        """Inicializa con dos clientes pre-creados.

        Los clientes deben ser creados externamente via
        quantum_helpers.create_client_from_config() para compartir MCPServer.

        Args:
            client_a: Primer cliente (angulo A)
            client_b: Segundo cliente (angulo B)
        """
        self.client_a = client_a
        self.client_b = client_b

    async def parallel_chat(
        self,
        prompt_a: str,
        system_a: str,
        prompt_b: str,
        system_b: str,
        max_steps: int = 50,
    ) -> DualResult:
        """Ejecuta dos chat_with_system() en paralelo.

        Cada llamada es independiente: historial local, sin mutar estado
        compartido. El MCPServer se comparte solo para lectura de herramientas.

        Args:
            prompt_a: Prompt del usuario para angulo A
            system_a: System prompt para angulo A
            prompt_b: Prompt del usuario para angulo B
            system_b: System prompt para angulo B
            max_steps: Maximo de iteraciones por chat

        Returns:
            DualResult con ambas respuestas
        """
        print("  [quantum] Ejecutando angulos A y B en paralelo...", file=sys.stderr)
        start_total = time.time()

        async def _run_angle(client, prompt, system, label):
            start = time.time()
            try:
                response = await client.chat_with_system(prompt, system, max_steps)
                duration = time.time() - start
                print(
                    f"  [quantum] Angulo {label}: {len(response)} chars en {duration:.1f}s",
                    file=sys.stderr,
                )
                return response, duration, None
            except Exception as e:
                duration = time.time() - start
                print(
                    f"  [quantum] Angulo {label}: ERROR en {duration:.1f}s — {e}",
                    file=sys.stderr,
                )
                return "", duration, str(e)

        result_a, result_b = await asyncio.gather(
            _run_angle(self.client_a, prompt_a, system_a, "A"),
            _run_angle(self.client_b, prompt_b, system_b, "B"),
        )

        total_duration = time.time() - start_total
        resp_a, dur_a, err_a = result_a
        resp_b, dur_b, err_b = result_b

        print(
            f"  [quantum] Total: {total_duration:.1f}s "
            f"(secuencial seria ~{dur_a + dur_b:.1f}s, "
            f"ahorro ~{max(0, (dur_a + dur_b) - total_duration):.1f}s)",
            file=sys.stderr,
        )

        return DualResult(
            response_a=resp_a,
            response_b=resp_b,
            duration_a=dur_a,
            duration_b=dur_b,
            total_duration=total_duration,
            error_a=err_a,
            error_b=err_b,
        )

    async def sequential_fallback(
        self,
        prompt: str,
        system_prompt: str,
        context_from_a: str = "",
        max_steps: int = 50,
    ) -> str:
        """Fallback secuencial: usa cliente A con contexto del intento previo.

        Se usa cuando el merge falla y necesitamos una respuesta completa
        usando el resultado del angulo A como contexto.

        Args:
            prompt: Prompt del usuario
            system_prompt: System prompt base
            context_from_a: Respuesta del angulo A como contexto
            max_steps: Maximo de iteraciones

        Returns:
            Respuesta completa
        """
        print("  [quantum] Fallback secuencial con contexto de A...", file=sys.stderr)

        enriched_system = system_prompt
        if context_from_a:
            # Limitar contexto (1M context → budget generoso)
            ctx = context_from_a[:60000]
            if len(context_from_a) > 60000:
                ctx += "\n\n[... respuesta anterior truncada ...]"
            enriched_system += (
                f"\n\n== CONTEXTO DE INTENTO PREVIO ==\n"
                f"Un colega ya implemento parte del codigo. "
                f"Usa su trabajo como base y COMPLETA lo que falta:\n{ctx}\n"
                f"== FIN CONTEXTO ==\n"
            )

        return await self.client_a.chat_with_system(
            prompt, enriched_system, max_steps
        )
