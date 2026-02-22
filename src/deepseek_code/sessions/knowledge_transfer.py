"""Cross-chat knowledge transfer between DeepSeek sessions.

Enables serializing what one chat "knows" (its summary + key decisions)
and injecting it into another chat as a special context injection.

Use case: Chat A designed a UI component. Chat B needs to implement
the API that matches Chat A's design. Transfer A's knowledge to B.

The transferred knowledge becomes a Phase 2 injection with type="knowledge".

Usage:
    from deepseek_code.sessions.knowledge_transfer import transfer_knowledge

    # In CLI with --transfer-from:
    injection = transfer_knowledge(store, "delegate:ui-module", "delegate:api-module")
    if injection:
        call_params["pending_injections"].append(injection)
"""

import time
from typing import Optional, List, Dict

from .session_store import SessionStore, ChatSession


def extract_knowledge(store: SessionStore, source_name: str) -> Optional[dict]:
    """Extract transferable knowledge from a source session.

    Returns a compact knowledge block with:
    - Source session name and topic
    - Summary of what the session knows/decided
    - Skills that were loaded (they contain domain knowledge)
    - Message count for context weight estimation

    Returns None if session not found.
    """
    session = store.get(source_name)
    if not session:
        return None

    skills = [
        c.split(":", 1)[1] for c in session.injected_contexts
        if c.startswith("skill:")
    ]

    memories = [
        c.split(":", 1)[1] for c in session.injected_contexts
        if c.startswith("memory:") or c.startswith("global:")
    ]

    return {
        "source": source_name,
        "topic": session.topic or source_name,
        "summary": session.summary or f"Sesion con {session.message_count} mensajes",
        "skills_loaded": skills,
        "memories_loaded": memories,
        "message_count": session.message_count,
        "extracted_at": time.time(),
    }


def format_knowledge_injection(knowledge: dict) -> dict:
    """Format extracted knowledge as a Phase 2 injection dict.

    Returns injection compatible with session_chat.py's pending_injections:
    {"type": "knowledge", "name": "from:<source>", "content": "..."}
    """
    skill_list = ", ".join(knowledge["skills_loaded"]) if knowledge["skills_loaded"] else "ninguna"
    memory_list = ", ".join(knowledge["memories_loaded"]) if knowledge["memories_loaded"] else "ninguna"

    content = (
        f"=== Conocimiento transferido de '{knowledge['source']}' ===\n"
        f"Tema: {knowledge['topic']}\n"
        f"Resumen: {knowledge['summary']}\n"
        f"Skills cargadas: {skill_list}\n"
        f"Memorias: {memory_list}\n"
        f"Mensajes intercambiados: {knowledge['message_count']}\n"
        f"=== Usa esta informacion como contexto adicional. "
        f"No repitas trabajo ya hecho en esa sesion. ==="
    )

    return {
        "type": "knowledge",
        "name": f"from:{knowledge['source']}",
        "content": content,
    }


def transfer_knowledge(
    store: SessionStore,
    source_name: str,
    target_name: str,
) -> Optional[dict]:
    """Extract from source and prepare injection for target.

    Also records the transfer in both sessions' metadata.

    Args:
        store: The session store
        source_name: Session to extract knowledge from
        target_name: Session to inject knowledge into

    Returns:
        The injection dict ready for pending_injections, or None if source not found.
    """
    knowledge = extract_knowledge(store, source_name)
    if not knowledge:
        return None

    injection = format_knowledge_injection(knowledge)

    # Record transfer in source session
    source = store.sessions.get(source_name)
    if source and target_name not in source.knowledge_sent_to:
        source.knowledge_sent_to.append(target_name)

    # Record receipt in target session (if already exists)
    target = store.sessions.get(target_name)
    if target and source_name not in target.knowledge_received_from:
        target.knowledge_received_from.append(source_name)

    store.save()
    return injection


def list_transferable_sessions(store: SessionStore) -> List[dict]:
    """List sessions that have enough context to transfer knowledge from.

    Only sessions with at least 2 messages and a summary are useful.
    """
    active = store.list_active()
    transferable = []
    for s in active:
        if s.message_count >= 2:
            transferable.append({
                "name": s.name,
                "topic": s.topic or s.name,
                "summary": s.summary or f"{s.message_count} mensajes",
                "skills": [c.split(":", 1)[1] for c in s.injected_contexts
                           if c.startswith("skill:")],
                "messages": s.message_count,
            })
    return transferable
