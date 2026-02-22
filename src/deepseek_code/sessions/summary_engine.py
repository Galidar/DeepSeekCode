"""Generates and maintains compact summaries of DeepSeek chat sessions.

Summaries are updated after message exchanges, stored in ChatSession.summary
and ChatSession.topic. They enable Claude to understand what each chat knows
without reading the full history.

Uses LOCAL heuristics (0 extra tokens) by default. Optionally can ask DeepSeek
to self-summarize (costs ~100 tokens per update).

Format:
    topic: "Authentication module with JWT"
    summary: "Designed login/register endpoints. Has jwt-patterns skill.
    Last: added password reset flow. Messages: 5"
"""

import re
import time
from typing import Optional

from .session_store import SessionStore, ChatSession


def should_update_summary(session: ChatSession, force: bool = False) -> bool:
    """Determine if a summary update is needed.

    Rules:
    - First summary: after 2 messages
    - Subsequent updates: every 3 messages or if forced
    - Never update closed sessions
    """
    if not session or session.status != "active":
        return False
    if force:
        return True
    if session.message_count < 2:
        return False
    if not session.summary:
        return True  # First summary
    # Update every 3 messages after the first summary
    return session.message_count % 3 == 0


def generate_local_summary(
    session: ChatSession,
    user_message: str,
    response: str,
) -> dict:
    """Generate summary without extra DeepSeek call (0 tokens).

    Heuristics:
    - topic: from first user message or session name
    - summary: last action type + skills loaded + message count
    - Classifies the exchange as code/explanation/error-fix/design

    Returns:
        {"topic": "...", "summary": "..."}
    """
    # Topic: use existing or derive from first message / session name
    topic = session.topic
    if not topic:
        # Extract meaningful topic from user message
        topic = _extract_topic(user_message)

    # Classify this exchange
    action_type = _classify_exchange(user_message, response)

    # List loaded skills
    skills = [
        c.split(":", 1)[1] for c in session.injected_contexts
        if c.startswith("skill:")
    ]

    # List loaded memories
    memories = [
        c.split(":", 1)[1] for c in session.injected_contexts
        if c.startswith("memory:") or c.startswith("global:")
    ]

    # Build compact summary
    parts = []
    if session.summary:
        # Append to existing summary (keep last 2 actions)
        existing_parts = session.summary.split(". ")
        # Keep only the last action from previous summary
        if len(existing_parts) > 2:
            parts.append(existing_parts[-2])
    parts.append(action_type)
    if skills:
        parts.append(f"Skills: {', '.join(skills[:3])}")
    if memories:
        parts.append(f"Memoria: {', '.join(memories[:2])}")
    parts.append(f"Msgs: {session.message_count}")

    summary = ". ".join(parts)

    return {"topic": topic, "summary": summary}


def update_session_summary(
    store: SessionStore,
    session_name: str,
    user_message: str,
    response: str,
    force: bool = False,
):
    """Update a session's summary if needed.

    Call this after each message exchange (Phase 3 response).
    Only updates if should_update_summary() returns True.
    """
    session = store.get(session_name)
    if not session:
        return

    if not should_update_summary(session, force):
        return

    summary_data = generate_local_summary(session, user_message, response)
    store.update_summary(
        session_name,
        topic=summary_data["topic"],
        summary=summary_data["summary"],
    )


def _extract_topic(message: str) -> str:
    """Extract a meaningful topic from a user message.

    Truncates to ~50 chars at word boundary.
    """
    # Remove common prefixes like "Implementa", "Crea", "Agrega"
    cleaned = message.strip()
    # Take first sentence or first 50 chars
    first_sentence = re.split(r'[.!?\n]', cleaned)[0].strip()
    if len(first_sentence) > 50:
        first_sentence = first_sentence[:50].rsplit(' ', 1)[0] + "..."
    return first_sentence or "Sin tema"


def _classify_exchange(user_message: str, response: str) -> str:
    """Classify the type of exchange for the summary.

    Returns a short description like:
    - "Genero codigo de autenticacion"
    - "Corrigio error TypeError"
    - "Diseño estructura de base de datos"
    """
    msg_lower = user_message.lower()
    resp_lower = response.lower()[:500] if response else ""

    # Error fix patterns
    if any(kw in msg_lower for kw in ["error", "fix", "bug", "corrig", "fallo", "crash"]):
        return f"Correccion: {user_message[:40]}"

    # Code generation patterns
    if any(kw in resp_lower for kw in ["```", "function ", "class ", "def ", "const ", "let "]):
        return f"Codigo: {user_message[:40]}"

    # Design/architecture patterns
    if any(kw in msg_lower for kw in ["diseñ", "design", "arquitect", "structur", "patron"]):
        return f"Diseño: {user_message[:40]}"

    # Default: describe the action
    return f"Consulta: {user_message[:40]}"
