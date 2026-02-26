"""Sesion multi-instancia: generalizacion de DualSession a N clientes.

Ejecuta N instancias de DeepSeek en paralelo con roles diferenciados.
Cada instancia tiene su propio client y system prompt, pero comparten
el mismo MCPServer (seguro para lecturas concurrentes via asyncio).

Uso:
    mcp = create_shared_mcp_server(config)
    clients = [create_client_from_config(config, mcp, f"C{i}") for i in range(3)]
    roles = preset_full_pipeline()
    session = MultiSession(list(zip(clients, roles)))
    result = await session.parallel_execute(task, base_system)
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from deepseek_code.client.deepseek_client import DeepSeekCodeClient
from .roles import SessionRole, RoleType


@dataclass
class InstanceResult:
    """Resultado de una instancia individual."""
    role_label: str
    role_type: str
    response: str
    duration: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.response)

    def to_dict(self) -> dict:
        result = {
            "role": self.role_label,
            "type": self.role_type,
            "duration_s": round(self.duration, 1),
            "chars": len(self.response),
            "success": self.success,
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class MultiResult:
    """Resultado agregado de una ejecucion multi-instancia."""
    results: List[InstanceResult]
    total_duration: float

    @property
    def all_success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def successful_results(self) -> List[InstanceResult]:
        return [r for r in self.results if r.success]

    def get_by_role(self, role_type: str) -> Optional[InstanceResult]:
        """Busca resultado por tipo de rol."""
        for r in self.results:
            if r.role_type == role_type:
                return r
        return None

    def to_dict(self) -> dict:
        return {
            "total_duration_s": round(self.total_duration, 1),
            "instances": len(self.results),
            "successful": len(self.successful_results),
            "results": [r.to_dict() for r in self.results],
        }


class MultiSession:
    """Gestiona N clientes DeepSeek con roles diferenciados.

    Generaliza DualSession: en vez de hardcodear 2 clientes,
    acepta una lista de (client, role) parejas.
    """

    def __init__(
        self,
        instances: List[Tuple[DeepSeekCodeClient, SessionRole]],
    ):
        """Inicializa con N parejas (client, role).

        Args:
            instances: Lista de (DeepSeekCodeClient, SessionRole)
        """
        self.instances = instances

    async def parallel_execute(
        self,
        task_prompt: str,
        base_system: str,
        context_per_role: Optional[Dict[str, str]] = None,
    ) -> MultiResult:
        """Ejecuta todas las instancias en paralelo.

        Cada instancia recibe:
            - base_system + role.system_suffix como system prompt
            - task_prompt como user message
            - Contexto extra opcional por rol

        Args:
            task_prompt: Prompt de la tarea (mismo para todos)
            base_system: System prompt base (se enriquece por rol)
            context_per_role: Dict {role_label: contexto_extra} (opcional)

        Returns:
            MultiResult con todos los resultados
        """
        context_per_role = context_per_role or {}
        n = len(self.instances)
        print(
            f"  [multi] Ejecutando {n} instancias en paralelo...",
            file=sys.stderr,
        )
        start_total = time.time()

        tasks = []
        for client, role in self.instances:
            system = base_system + role.system_suffix
            extra = context_per_role.get(role.label, "")
            if extra:
                system += f"\n\nCONTEXT:\n{extra}"
            tasks.append(
                self._run_instance(client, task_prompt, system, role)
            )

        results = await asyncio.gather(*tasks)
        total_duration = time.time() - start_total

        # Calcular ahorro vs secuencial
        seq_time = sum(r.duration for r in results)
        print(
            f"  [multi] Total: {total_duration:.1f}s "
            f"(secuencial: ~{seq_time:.1f}s, "
            f"ahorro: ~{max(0, seq_time - total_duration):.1f}s)",
            file=sys.stderr,
        )

        return MultiResult(results=list(results), total_duration=total_duration)

    async def sequential_pipeline(
        self,
        task_prompt: str,
        base_system: str,
    ) -> MultiResult:
        """Ejecuta instancias secuencialmente, pasando output como contexto.

        Util para flujos tipo: generate -> review -> fix.
        El output del paso N se pasa como contexto al paso N+1.

        Args:
            task_prompt: Prompt de la tarea
            base_system: System prompt base

        Returns:
            MultiResult con todos los resultados
        """
        # Ordenar por prioridad (mayor primero)
        sorted_instances = sorted(
            self.instances, key=lambda x: -x[1].priority,
        )

        print(
            f"  [multi] Pipeline secuencial: "
            f"{' -> '.join(r.label for _, r in sorted_instances)}",
            file=sys.stderr,
        )
        start_total = time.time()
        results = []
        accumulated_context = ""

        for client, role in sorted_instances:
            system = base_system + role.system_suffix
            if accumulated_context:
                system += (
                    f"\n\nPREVIOUS OUTPUT:\n"
                    f"{accumulated_context[:60000]}"
                )

            result = await self._run_instance(
                client, task_prompt, system, role,
            )
            results.append(result)

            if result.success:
                accumulated_context = result.response

        total_duration = time.time() - start_total
        return MultiResult(results=results, total_duration=total_duration)

    async def _run_instance(
        self,
        client: DeepSeekCodeClient,
        prompt: str,
        system: str,
        role: SessionRole,
    ) -> InstanceResult:
        """Ejecuta una instancia individual.

        Args:
            client: Cliente DeepSeek
            prompt: Prompt del usuario
            system: System prompt completo (base + rol)
            role: Rol de la instancia

        Returns:
            InstanceResult
        """
        start = time.time()
        try:
            response = await client.chat_with_system(
                prompt, system, role.max_steps,
            )
            duration = time.time() - start
            print(
                f"  [multi] {role.label}: "
                f"{len(response)} chars en {duration:.1f}s",
                file=sys.stderr,
            )
            return InstanceResult(
                role_label=role.label,
                role_type=role.role_type.value,
                response=response,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            print(
                f"  [multi] {role.label}: ERROR en {duration:.1f}s — {e}",
                file=sys.stderr,
            )
            return InstanceResult(
                role_label=role.label,
                role_type=role.role_type.value,
                response="",
                duration=duration,
                error=str(e),
            )
