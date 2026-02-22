"""Cliente DeepSeek unificado con soporte para API key y sesion web."""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union

from openai import AsyncOpenAI

from ..server.protocol import MCPServer, MCPRequest, MCPMethod
from .web_session import DeepSeekWebSession, TokenExpiredError
from .web_tool_caller import (
    build_tools_prompt, build_web_prompt, extract_tool_calls,
    format_tool_result, clean_final_response
)
from .context_manager import (
    estimate_tokens, total_estimated_tokens, build_summary_prompt,
    should_summarize, rebuild_history_after_summary, make_memory_entry,
    format_summary_notification, SUMMARY_MAX_TOKENS
)
from ..skills.skill_injector import build_skills_context
from .task_classifier import classify_task, TaskLevel
from .prompt_builder import build_adaptive_system_prompt
from .api_caller import build_api_params

# Limites de contexto segun modo de operacion
# API: 128K tokens (deepseek-chat via API)
# Web (App/Chat): ~1M tokens (interfaz web de DeepSeek)
API_MAX_TOKENS = 131072
WEB_MAX_TOKENS = 1000000
# Umbral por defecto (80%) — a partir de aqui se activa resumen progresivo
DEFAULT_SUMMARY_THRESHOLD = 80


class DeepSeekCodeClient:
    """Cliente unificado que puede usar API key o sesion web."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        mcp_server: Optional[MCPServer] = None,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        memory_path: Optional[str] = None,
        summary_threshold: int = DEFAULT_SUMMARY_THRESHOLD,
        skills_dir: Optional[str] = None,
        session_manager=None,
        # Parametros para modo web:
        bearer_token: Optional[str] = None,
        cookies: Optional[dict] = None,
        wasm_path: Union[str, Path] = "sha3_wasm_bg.wasm",
        config: Optional[dict] = None,
    ):
        self.mcp = mcp_server
        self.model = model
        self.config = config or {}
        self.memory_path = Path(memory_path).expanduser().resolve() if memory_path else None
        self.skills_dir = skills_dir
        self.summary_threshold = max(10, min(95, summary_threshold))
        self.session_manager = session_manager

        # Modo de operacion
        if bearer_token and cookies:
            self.mode = "web"
            self.web_session = DeepSeekWebSession(bearer_token, cookies, wasm_path)
            self.api_client = None
        elif api_key:
            self.mode = "api"
            self.web_session = None
            self.api_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        else:
            raise ValueError("Debe proporcionar api_key o (bearer_token + cookies)")

        # Limite de contexto segun modo
        self.max_context_tokens = WEB_MAX_TOKENS if self.mode == "web" else API_MAX_TOKENS

        # Cargar memoria si existe
        self.memory_content = self._load_memory()
        self.system_message = self._build_system_message()
        self.conversation_history: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_message}
        ]
        self.available_tools = None
        self.summary_count = 0
        # Maximo de resumenes: proporcional al contexto disponible
        # Web (1M) = 10 resumenes, API (128K) = 3
        self.max_summaries = 10 if self.mode == "web" else 3

    def _load_memory(self) -> str:
        if not self.memory_path or not self.memory_path.exists():
            return ""
        try:
            with open(self.memory_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            return ""

    def _save_memory(self, content: str):
        if not self.memory_path:
            return
        try:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.memory_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.memory_content = content
        except Exception as e:
            print(f"Error guardando memoria: {e}")

    def _build_system_message(self, override: Optional[str] = None, user_message: Optional[str] = None) -> str:
        """Construye system prompt adaptivo segun complejidad del mensaje."""
        if override:
            # Override directo (delegacion, agente, etc.)
            base = override
            if self.skills_dir and user_message:
                skills_context = build_skills_context(
                    self.skills_dir, user_message, mode=self.mode,
                    task_level="delegation",
                )
                if skills_context:
                    base += skills_context
            if self.memory_content:
                base += f"\n\n**Memoria persistente:**\n{self.memory_content}"
            return base

        # Clasificar la tarea para adaptar el prompt
        task_level = classify_task(user_message or "")
        level_name = task_level.name.lower()

        # Construir skills context solo si el nivel lo amerita
        skills_ctx = ""
        if self.skills_dir and user_message and task_level.value >= TaskLevel.CODE_SIMPLE.value:
            skills_ctx = build_skills_context(
                self.skills_dir, user_message,
                mode=self.mode, task_level=level_name,
            )

        return build_adaptive_system_prompt(
            task_level, user_message or "",
            skills_context=skills_ctx,
            memory_content=self.memory_content,
            skills_dir=self.skills_dir or "",
        )

    async def _generate_summary(self, messages: List[Dict]) -> str:
        """Genera un resumen usando el modelo (API o web)."""
        if not messages:
            return ""
        prompt = build_summary_prompt(messages)
        try:
            if self.mode == "api":
                response = await self.api_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=SUMMARY_MAX_TOKENS,
                    temperature=0.3
                )
                return response.choices[0].message.content.strip()
            else:
                import asyncio
                return await asyncio.get_event_loop().run_in_executor(
                    None, self.web_session.chat, prompt
                )
        except Exception as e:
            print(f"Error generando resumen: {e}")
            return ""

    async def _check_context_and_summarize(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """Resumen progresivo: comprime la primera mitad del historial."""
        tokens_before = total_estimated_tokens(self.conversation_history)
        result = should_summarize(
            self.conversation_history, self.max_context_tokens,
            self.summary_threshold, self.summary_count, self.max_summaries
        )
        if result is None:
            return False, None, None

        to_summarize, to_keep = result
        summary = await self._generate_summary(to_summarize)
        if not summary:
            return False, None, None

        # Guardar resumen en memoria persistente
        self._save_memory(self.memory_content + make_memory_entry(summary))
        self.system_message = self._build_system_message()

        # Reconstruir historial
        self.conversation_history = rebuild_history_after_summary(
            self.system_message, summary, to_keep
        )
        self.summary_count += 1

        tokens_after = total_estimated_tokens(self.conversation_history)
        notification = format_summary_notification(
            self.summary_count, len(to_summarize),
            tokens_before, tokens_after, self.max_context_tokens
        )
        return True, notification, None

    def invalidate_tools_cache(self):
        """Invalida la cache de herramientas para forzar re-descubrimiento."""
        self.available_tools = None

    async def _get_tools(self) -> List[Dict]:
        if not self.mcp:
            return []
        if self.available_tools is None:
            request = MCPRequest(id=1, method=MCPMethod.TOOLS_LIST)
            response = await self.mcp.handle_request(request)
            if hasattr(response, 'error'):
                raise Exception(f"Error obteniendo herramientas: {response.error}")
            self.available_tools = response.result["tools"]
        return self.available_tools

    async def _format_tools_for_deepseek(self) -> List[Dict]:
        tools = await self._get_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"]
                }
            }
            for t in tools
        ]

    async def chat(self, user_message: str, max_steps: int = 10) -> str:
        """Metodo principal de chat con herramientas y resumen automatico."""
        # Resumen progresivo: no interrumpe la conversacion, solo comprime
        resumen_hecho, notificacion, _ = await self._check_context_and_summarize()
        if resumen_hecho and notificacion:
            print(f"\n  {notificacion}\n")

        # Auto-inyectar skills relevantes en el system message
        if self.skills_dir:
            updated_sys = self._build_system_message(user_message=user_message)
            if updated_sys != self.system_message:
                self.system_message = updated_sys
                self.conversation_history[0] = {"role": "system", "content": self.system_message}

        self.conversation_history.append({"role": "user", "content": user_message})

        if self.mode == "api":
            return await self._chat_api(max_steps)
        else:
            return await self._chat_web(max_steps)

    async def chat_with_system(self, user_message: str, system_prompt: str, max_steps: int = 10) -> str:
        """Chat con system prompt personalizado (para agentes). Historial independiente."""
        if self.mode == "api":
            return await self._chat_with_system_api(user_message, system_prompt, max_steps)
        else:
            return await self._chat_with_system_web(user_message, system_prompt, max_steps)

    async def _run_tool(self, tool_call_id, tool_name, arguments):
        """Ejecuta una herramienta MCP y retorna el resultado como string."""
        request = MCPRequest(
            id=tool_call_id, method=MCPMethod.TOOLS_CALL,
            params={"name": tool_name, "arguments": arguments}
        )
        resp = await self.mcp.handle_request(request)
        if hasattr(resp, 'error'):
            return f"Error: {resp.error.message}"
        result = resp.result
        return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)

    async def _chat_with_system_api(self, user_message: str, system_prompt: str, max_steps: int) -> str:
        """chat_with_system en modo API (historial independiente)."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        tools = await self._format_tools_for_deepseek()

        for step in range(max_steps):
            params = build_api_params(self.model, messages, tools, TaskLevel.DELEGATION, self.config)
            response = await self.api_client.chat.completions.create(**params)
            msg = response.choices[0].message
            if not msg.tool_calls:
                return msg.content
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })
            for tc in msg.tool_calls:
                content_str = await self._run_tool(tc.id, tc.function.name, json.loads(tc.function.arguments))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content_str})

        return "Se alcanzo el numero maximo de iteraciones."

    async def _chat_with_system_web(self, user_message: str, system_prompt: str, max_steps: int) -> str:
        """chat_with_system en modo web (delega a run_agent_web)."""
        from .web_tool_caller import run_agent_web
        tools = await self._get_tools()
        return await run_agent_web(
            self.web_session, self.mcp, system_prompt,
            user_message, tools, max_steps
        )

    async def _chat_api(self, max_steps: int) -> str:
        """Modo API key con auto-select de modelo y max_tokens."""
        # Clasificar nivel de tarea del ultimo mensaje para params API
        last_user = next((m["content"] for m in reversed(self.conversation_history) if m["role"] == "user"), "")
        task_level = classify_task(last_user)
        for step in range(max_steps):
            messages = self.conversation_history.copy()
            tools = await self._format_tools_for_deepseek()
            params = build_api_params(self.model, messages, tools, task_level, self.config)
            response = await self.api_client.chat.completions.create(**params)
            msg = response.choices[0].message
            if not msg.tool_calls:
                self.conversation_history.append({"role": "assistant", "content": msg.content})
                return msg.content

            self.conversation_history.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in message.tool_calls
                ]
            })
            for tc in message.tool_calls:
                content_str = await self._run_tool(tc.id, tc.function.name, json.loads(tc.function.arguments))
                self.conversation_history.append({"role": "tool", "tool_call_id": tc.id, "content": content_str})

        return "Se alcanzo el numero maximo de iteraciones sin respuesta final."

    async def _chat_web(self, max_steps: int) -> str:
        """Modo sesion web con tool calling simulado por texto."""
        import asyncio

        # Verificar sesion antes de cada operacion web
        if self.session_manager:
            valid = await self.session_manager.ensure_valid_session()
            if not valid:
                return "Sesion expirada. Ejecuta /login para renovar."

        # Construir prompt de herramientas (una sola vez)
        tools = await self._get_tools()
        tools_prompt = build_tools_prompt(tools) if tools else ""

        for step in range(max_steps):
            # Construir prompt completo con system + historial + herramientas
            prompt = build_web_prompt(
                self.system_message,
                self.conversation_history,
                tools_prompt
            )

            # Enviar al modo web (con thinking_enabled configurable)
            use_thinking = self.config.get("thinking_enabled", True)
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self.web_session.chat, prompt, use_thinking
                )
            except TokenExpiredError as e:
                return f"[Error de sesion] {e}. Ejecuta /login para renovar."

            # Extraer tool calls de la respuesta
            tool_calls, clean_text = extract_tool_calls(response)

            if not tool_calls:
                # Sin tool calls: respuesta final — limpiar JSON crudo si hay
                cleaned = clean_final_response(response) if step > 0 else response
                self.conversation_history.append({"role": "assistant", "content": cleaned})
                return cleaned

            # Ejecutar cada herramienta y agregar resultados al historial
            if clean_text:
                self.conversation_history.append({"role": "assistant", "content": clean_text})

            for call in tool_calls:
                tool_name = call["tool"]
                arguments = call["args"]

                tool_request = MCPRequest(
                    id=f"web_{step}_{tool_name}",
                    method=MCPMethod.TOOLS_CALL,
                    params={"name": tool_name, "arguments": arguments}
                )
                tool_response = await self.mcp.handle_request(tool_request)

                if hasattr(tool_response, 'error'):
                    result_str = f"Error: {tool_response.error.message}"
                else:
                    result = tool_response.result
                    result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)

                # Agregar resultado al historial para el siguiente turno
                formatted = format_tool_result(tool_name, result_str)
                self.conversation_history.append({"role": "tool_result", "content": formatted})
                print(f"  [herramienta] {tool_name} -> {len(result_str)} chars")

        return "Se alcanzo el numero maximo de iteraciones en modo web."
