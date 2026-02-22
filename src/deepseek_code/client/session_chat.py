"""Session-aware chat for DeepSeek web mode with full continuity.

Integrates SessionStore with DeepSeekWebSession to provide:
- Persistent sessions across CLI invocations
- System prompt sent only once per session
- parent_message_id chaining for conversation continuity
- Tool calling within sessions
- Multiple parallel sessions

Usage from DeepSeekCodeClient:
    response = await client.chat_in_session("auth-module", "create login endpoint",
                                             system_prompt=enriched_system)
    # Later, in another CLI call:
    response = await client.chat_in_session("auth-module", "add password reset")
    # DeepSeek has full context from the first call
"""

import asyncio
import json
import os
import re
import sys
import time
from typing import Optional, List, Dict

from ..sessions.session_store import SessionStore, ChatSession
from .web_session import DeepSeekWebSession, TokenExpiredError
from .web_tool_caller import (
    build_tools_prompt, extract_tool_calls,
    format_tool_result, clean_final_response,
)

# Patterns that should NEVER appear in Phase 3 (user task) messages.
# These are acknowledgment instructions meant only for Phase 1/2.
_PHASE3_STRIP_PATTERNS = [
    # Spanish variations
    r',?\s*(?:di|responde|contesta|dime)\s+(?:solo|solamente|unicamente)\s+["\']?OK["\']?\.?',
    r',?\s*responde\s+unicamente\s*:?\s*["\']?OK["\']?\.?',
    r',?\s*solo\s+(?:di|responde|contesta)\s+["\']?OK["\']?\.?',
    # English variations
    r',?\s*(?:just\s+)?(?:say|respond|reply)\s+(?:only\s+)?["\']?OK["\']?\.?',
    # Generic "solo OK" / "only OK" at end of message
    r',?\s+(?:solo|only)\s+["\']?OK["\']?\s*\.?\s*$',
]
_PHASE3_RE = re.compile('|'.join(_PHASE3_STRIP_PATTERNS), re.IGNORECASE)


def _sanitize_phase3(message: str) -> str:
    """Remove acknowledgment instructions accidentally appended to task messages.

    AI agents (like Claude Code) sometimes append "di solo OK" or similar
    phrases when constructing delegate commands.  DeepSeek then literally
    obeys and responds "OK" instead of executing the task.

    This function strips those patterns so Phase 3 only contains the task.
    """
    cleaned = _PHASE3_RE.sub('', message).strip()
    # If stripping removed everything (edge case), return original
    return cleaned if cleaned else message


def get_session_store_path() -> str:
    """Get the path to the sessions store file."""
    appdata = os.environ.get('APPDATA')
    if appdata:
        base = os.path.join(appdata, 'DeepSeek-Code')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config', 'DeepSeek-Code')
    return os.path.join(base, 'sessions.json')


def get_session_store() -> SessionStore:
    """Get or create the global session store."""
    return SessionStore(get_session_store_path())


async def chat_in_session(
    web_session: DeepSeekWebSession,
    mcp_server,
    session_name: str,
    user_message: str,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict]] = None,
    max_steps: int = 10,
    thinking_enabled: bool = True,
    session_manager=None,
    pending_injections: Optional[List[Dict]] = None,
) -> str:
    """Chat within a named session with full conversation continuity.

    Flow per message:
    1. System prompt → "OK" (first message only)
    2. Context injections → "Skill X aceptada" (only new ones)
    3. User message (clean, just the text)

    Args:
        web_session: The DeepSeek web session for HTTP communication
        mcp_server: MCP server for tool execution
        session_name: Name of the session (e.g. "auth-module", "chat-1")
        user_message: The user's message
        system_prompt: System prompt (only sent on first message of session)
        tools: Available tools for tool calling
        max_steps: Max tool-calling iterations
        thinking_enabled: Enable DeepSeek thinking mode
        session_manager: Optional session manager for auth validation
        pending_injections: Context blocks to inject before user message.
            Each dict: {"type": "skill"|"memory"|"error", "name": "...", "content": "..."}

    Returns:
        The assistant's response text
    """
    # Validate session if manager available
    if session_manager:
        valid = await session_manager.ensure_valid_session()
        if not valid:
            return "Sesion expirada. Ejecuta /login para renovar."

    store = get_session_store()
    store.cleanup_old(max_age_hours=48)
    session = store.get(session_name)

    if not session:
        # Create new DeepSeek chat session
        chat_session_id = web_session.create_chat_session()
        session = store.create(session_name, chat_session_id)
        print(f"  [session] Nueva sesion '{session_name}' creada", file=sys.stderr)
    else:
        print(
            f"  [session] Reanudando '{session_name}' "
            f"(mensajes: {session.message_count})",
            file=sys.stderr,
        )

    # Set web_session to use this chat session
    web_session._chat_session_id = session.chat_session_id

    # --- Phase 1: System prompt initialization (first message only) ---
    if not session.system_prompt_sent and system_prompt:
        tools_prompt = build_tools_prompt(tools) if tools else ""
        init_prompt = system_prompt + tools_prompt + (
            "\n\nResponde UNICAMENTE 'OK' para confirmar que entendiste "
            "tus instrucciones y herramientas."
        )
        print(f"  [session] Enviando prompt tecnico...", file=sys.stderr)
        try:
            _init_response = await asyncio.get_event_loop().run_in_executor(
                None, web_session.chat, init_prompt,
                thinking_enabled, session.parent_message_id,
            )
        except TokenExpiredError as e:
            return f"[Error de sesion] {e}. Ejecuta /login para renovar."

        init_msg_id = web_session.last_message_id
        store.update(session_name, parent_message_id=init_msg_id)
        # Track system prompt tokens
        import math
        session_obj = store.sessions.get(session_name)
        if session_obj:
            session_obj.system_prompt_tokens = math.ceil(len(init_prompt) / 3.5)
            store.save()
        session = store.get(session_name)
        print(f"  [session] Prompt tecnico aceptado (~{math.ceil(len(init_prompt)/3.5)} tokens)", file=sys.stderr)

    # --- Phase 2: Context injections (skills, memory, errors, etc.) ---
    if pending_injections:
        already = set(session.injected_contexts or [])
        injected_tokens = 0
        for injection in pending_injections:
            ctx_id = f"{injection['type']}:{injection['name']}"
            if ctx_id in already:
                continue

            ctx_type = injection["type"].capitalize()
            ctx_name = injection["name"]

            # Type-specific acknowledgment prompts
            ack_map = {
                "skill": f"Skill {ctx_name} aceptada",
                "memory": f"Memoria {ctx_name} integrada",
                "global": f"Perfil {ctx_name} integrado",
                "error": f"Errores de {ctx_name} registrados",
                "knowledge": f"Conocimiento de {ctx_name} integrado",
            }
            ack_text = ack_map.get(injection["type"], f"{ctx_type} {ctx_name} aceptada")

            inject_prompt = (
                f"== {ctx_type.upper()}: {ctx_name} ==\n\n"
                f"{injection['content']}\n\n"
                f"== FIN {ctx_type.upper()} ==\n\n"
                f"Responde UNICAMENTE: '{ack_text}'"
            )

            print(f"  [session] Inyectando {injection['type']} '{ctx_name}'...", file=sys.stderr)
            try:
                _inject_response = await asyncio.get_event_loop().run_in_executor(
                    None, web_session.chat, inject_prompt,
                    thinking_enabled, session.parent_message_id,
                )
            except TokenExpiredError as e:
                return f"[Error de sesion] {e}. Ejecuta /login para renovar."

            inject_msg_id = web_session.last_message_id
            store.update(session_name, parent_message_id=inject_msg_id,
                         add_context=ctx_id)
            # Track injected tokens
            import math
            injected_tokens += math.ceil(len(injection.get("content", "")) / 3.5)
            session = store.get(session_name)
            print(f"  [session] {ack_text}", file=sys.stderr)

        # Update total injected tokens on session
        if injected_tokens > 0 and session:
            session.total_injected_tokens += injected_tokens
            store.save()

    # --- Phase 3: User message (clean) ---
    # Sanitize: strip acknowledgment patterns that an AI agent might
    # accidentally append to the task message (e.g. "di solo OK",
    # "responde unicamente OK").  These belong in Phase 1/2 only.
    prompt = _sanitize_phase3(user_message)

    # Tool-calling loop
    for step in range(max_steps):
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, web_session.chat, prompt,
                thinking_enabled, session.parent_message_id,
            )
        except TokenExpiredError as e:
            return f"[Error de sesion] {e}. Ejecuta /login para renovar."

        # Capture message_id for continuity
        msg_id = web_session.last_message_id

        # Extract tool calls
        tool_calls, clean_text = extract_tool_calls(response)

        if not tool_calls:
            # Final response — update session and return
            store.update(session_name, parent_message_id=msg_id)
            cleaned = clean_final_response(response) if step > 0 else response

            # Auto-update summary (0 extra tokens, local heuristics)
            try:
                from ..sessions.summary_engine import update_session_summary
                update_session_summary(store, session_name, user_message, cleaned)
            except Exception:
                pass  # fail-safe: summaries are nice-to-have

            return cleaned

        # Execute tools
        results = []
        for call in tool_calls:
            from ..server.protocol import MCPRequest, MCPMethod
            tool_request = MCPRequest(
                id=f"session_{session_name}_{step}_{call['tool']}",
                method=MCPMethod.TOOLS_CALL,
                params={"name": call["tool"], "arguments": call["args"]},
            )
            tool_response = await mcp_server.handle_request(tool_request)

            if hasattr(tool_response, 'error'):
                result_str = f"Error: {tool_response.error.message}"
            else:
                result = tool_response.result
                result_str = (
                    json.dumps(result, ensure_ascii=False)
                    if isinstance(result, dict) else str(result)
                )

            results.append(format_tool_result(call["tool"], result_str))
            print(
                f"  [session:{session_name}] {call['tool']} -> {len(result_str)} chars",
                file=sys.stderr,
            )

        # Update session state after this step
        store.update(session_name, parent_message_id=msg_id)

        # Next prompt is the tool results (sent in the same session)
        prompt = "\n".join(results)

    return "Se alcanzo el maximo de iteraciones en la sesion."


def list_sessions_json() -> dict:
    """List all sessions as a JSON-serializable dict."""
    store = get_session_store()
    store.cleanup_old(max_age_hours=48)
    return store.summary()


def close_session(name: str) -> dict:
    """Close a specific session."""
    store = get_session_store()
    if store.close(name):
        return {"success": True, "closed": name}
    return {"success": False, "error": f"Sesion '{name}' no encontrada"}


def close_all_sessions() -> dict:
    """Close all active sessions."""
    store = get_session_store()
    count = store.close_all()
    return {"success": True, "closed_count": count}
