"""Motor de ejecucion de agentes autonomos para DeepSeek MCP."""

import asyncio
import time
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, List

from .prompts import AGENT_SYSTEM_PROMPT, build_step_prompt
from .logger import AgentLogger


def _build_continuation_prompt(goal: str, step_num: int) -> str:
    """Prompt ligero para steps de continuacion.

    Cuando la sesion se mantiene via parent_message_id, DeepSeek ya tiene
    todo el contexto de pasos anteriores. No necesitamos re-enviar resúmenes.
    """
    return (
        f"PASO {step_num} — Continua con la META: {goal}\n\n"
        f"Basandote en todo lo que ya hiciste en pasos anteriores, "
        f"decide que hacer ahora. Si ya completaste la meta, "
        f"incluye COMPLETADO en tu respuesta con un resumen final."
    )


class AgentStatus(Enum):
    PLANNING = "planificando"
    EXECUTING = "ejecutando"
    COMPLETED = "completado"
    FAILED = "fallido"
    INTERRUPTED = "interrumpido"
    MAX_STEPS = "limite_alcanzado"


@dataclass
class AgentStep:
    """Registro de un paso del agente."""
    step_number: int
    response: str
    timestamp: str
    duration_ms: int


@dataclass
class AgentResult:
    """Resultado final de la ejecucion del agente."""
    goal: str
    status: AgentStatus
    steps: List[AgentStep]
    final_summary: str
    total_duration_s: float
    log_file: Optional[str] = None
    error: Optional[str] = None


class AgentEngine:
    """
    Motor de ejecucion autonoma. Recibe una meta del usuario
    y ejecuta pasos hasta completarla o alcanzar el limite.

    Usa client.chat_with_system() para cada paso, con un system prompt
    especial que instruye al LLM a actuar de forma autonoma.
    """

    def __init__(
        self,
        client,  # DeepSeekCodeClient
        max_steps: int = 50,
        min_delay_ms: int = 500,
        logs_dir: Optional[str] = None,
        on_step: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
    ):
        self.client = client
        self.max_steps = min(max_steps, 200)  # Tope absoluto: 200
        self.min_delay_ms = min_delay_ms
        self.on_step = on_step
        self.on_status = on_status
        self._interrupted = False
        self._steps: List[AgentStep] = []
        self._results: List[str] = []
        self._continue_parent_id: Optional[int] = None  # Session continuation

        # Logger
        self.logger = AgentLogger(logs_dir) if logs_dir else None

    def interrupt(self):
        """Llamado por Ctrl+C para detener el agente limpiamente."""
        self._interrupted = True

    async def run(self, goal: str) -> AgentResult:
        """Ejecuta el agente con la meta dada.

        Mantiene UNA sola sesion DeepSeek web a traves de todos los steps
        via continue_parent_id. Phase 1 solo se ejecuta en el step 1.
        """
        start_time = time.time()
        self._interrupted = False
        self._steps = []
        self._results = []
        self._continue_parent_id = None

        # Notificar inicio
        await self._notify_status(AgentStatus.PLANNING)

        for step_num in range(1, self.max_steps + 1):
            # Verificar interrupcion
            if self._interrupted:
                return self._finalize(goal, AgentStatus.INTERRUPTED,
                                      "Interrumpido por el usuario.", start_time)

            await self._notify_status(AgentStatus.EXECUTING)

            # Construir prompt: paso 1 = completo, paso N = ligero (DeepSeek ya tiene contexto)
            if self._continue_parent_id is None:
                step_prompt = build_step_prompt(goal, step_num, self._results)
            else:
                step_prompt = _build_continuation_prompt(goal, step_num)

            # Ejecutar paso
            step_start = time.time()
            try:
                response = await self.client.chat_with_system(
                    user_message=step_prompt,
                    system_prompt=AGENT_SYSTEM_PROMPT,
                    max_steps=50,
                    continue_parent_id=self._continue_parent_id,
                )
            except Exception as e:
                return self._finalize(goal, AgentStatus.FAILED,
                                      f"Error en paso {step_num}: {e}", start_time,
                                      error=str(e))

            # Capturar parent_id para continuacion del siguiente step
            if hasattr(self.client, 'web_session') and self.client.web_session:
                self._continue_parent_id = getattr(
                    self.client.web_session, 'last_message_id', None
                )

            step_duration = int((time.time() - step_start) * 1000)

            # Registrar paso (guardar hasta 20000 chars para el log)
            step_record = AgentStep(
                step_number=step_num,
                response=response[:20000] if response else "",
                timestamp=datetime.now().isoformat(),
                duration_ms=step_duration
            )
            self._steps.append(step_record)
            self._results.append(response or "")

            # Notificar progreso
            await self._notify_step(step_record)

            # Verificar si el agente decidio que termino
            if response and "COMPLETADO" in response.upper():
                return self._finalize(goal, AgentStatus.COMPLETED,
                                      response, start_time)

            # Delay minimo entre pasos (evitar spam de API)
            if self.min_delay_ms > 0:
                await asyncio.sleep(self.min_delay_ms / 1000)

        # Limite de pasos alcanzado
        last_response = self._results[-1] if self._results else "Sin respuesta"
        return self._finalize(
            goal, AgentStatus.MAX_STEPS,
            f"Se alcanzaron {self.max_steps} pasos. Ultimo resultado:\n{last_response[:3000]}",
            start_time
        )

    def _finalize(self, goal: str, status: AgentStatus, summary: str,
                  start_time: float, error: Optional[str] = None) -> AgentResult:
        """Construye el resultado final y guarda el log."""
        duration = time.time() - start_time
        log_file = None

        if self.logger:
            try:
                log_file = self.logger.save(
                    goal=goal,
                    steps=[
                        {
                            "step": s.step_number,
                            "response": s.response,
                            "timestamp": s.timestamp,
                            "duration_ms": s.duration_ms
                        }
                        for s in self._steps
                    ],
                    status=status.value,
                    summary=summary[:10000],
                    duration_s=duration,
                    error=error
                )
            except Exception:
                pass

        return AgentResult(
            goal=goal,
            status=status,
            steps=self._steps,
            final_summary=summary,
            total_duration_s=duration,
            log_file=log_file,
            error=error
        )

    async def _notify_status(self, status: AgentStatus):
        """Notifica cambio de estado via callback."""
        if self.on_status:
            try:
                result = self.on_status(status)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def _notify_step(self, step: AgentStep):
        """Notifica paso completado via callback."""
        if self.on_step:
            try:
                result = self.on_step(step)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
