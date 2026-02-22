"""Persistent multi-session store for DeepSeek Code conversations.

Maintains named sessions with chat_session_id and parent_message_id
for conversation continuity across CLI invocations. Each session is
a separate DeepSeek web chat thread that persists on disk.

Usage:
    store = SessionStore("/path/to/sessions.json")
    session = store.create("auth-module", "uuid-from-deepseek")
    store.update("auth-module", parent_message_id="msg-uuid")
    session = store.get("auth-module")  # Retrieves with state
"""

import json
import os
import time
from typing import Optional, Dict, List, Union
from dataclasses import dataclass, field, asdict


@dataclass
class ChatSession:
    """A single persistent conversation session with DeepSeek."""
    name: str
    chat_session_id: str
    parent_message_id: Optional[Union[str, int]] = None
    system_prompt_sent: bool = False
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    status: str = "active"
    injected_contexts: List[str] = field(default_factory=list)

    # --- v2.6: Mode isolation, summaries, knowledge transfer ---
    mode: str = "chat"                    # Namespace: chat, oneshot, delegate, converse, quantum, multi-step
    topic: str = ""                       # One-line topic descriptor
    summary: str = ""                     # Compact summary of what this chat knows/decided
    summary_updated_at: float = 0.0       # Timestamp of last summary update
    knowledge_received_from: List[str] = field(default_factory=list)
    knowledge_sent_to: List[str] = field(default_factory=list)
    system_prompt_tokens: int = 0         # Estimated tokens of system prompt sent
    total_injected_tokens: int = 0        # Running total of context tokens injected


class SessionStore:
    """Manages multiple persistent chat sessions on disk.

    Sessions survive across CLI invocations, enabling conversation
    continuity. Each session maps to a DeepSeek web chat thread.
    """

    def __init__(self, store_path: str):
        self.store_path = store_path
        self.sessions: Dict[str, ChatSession] = {}
        self._load()

    def _load(self):
        """Load sessions from disk."""
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for name, sdata in data.get("sessions", {}).items():
                self.sessions[name] = ChatSession(**sdata)
        except (json.JSONDecodeError, KeyError, TypeError):
            self.sessions = {}

    def save(self):
        """Persist sessions to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(self.store_path)), exist_ok=True)
        data = {"sessions": {n: asdict(s) for n, s in self.sessions.items()}}
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def create(self, name: str, chat_session_id: str) -> ChatSession:
        """Create a new named session.

        Auto-detects mode from namespace prefix (e.g. 'delegate:auth' -> mode='delegate').
        """
        # Extract mode from namespace prefix
        mode = "chat"
        if ":" in name:
            prefix = name.split(":")[0]
            valid_modes = {"chat", "oneshot", "delegate", "converse", "quantum", "multi-step"}
            if prefix in valid_modes:
                mode = prefix
        session = ChatSession(name=name, chat_session_id=chat_session_id, mode=mode)
        self.sessions[name] = session
        self.save()
        return session

    def get(self, name: str) -> Optional[ChatSession]:
        """Get an active session by name. Returns None if not found or inactive."""
        session = self.sessions.get(name)
        if session and session.status != "active":
            return None
        return session

    def get_or_create(self, name: str, create_chat_fn) -> ChatSession:
        """Get existing session or create new one using the factory function.

        Args:
            name: Session name
            create_chat_fn: Callable that returns a new chat_session_id (str)
        """
        session = self.get(name)
        if session:
            return session
        chat_session_id = create_chat_fn()
        return self.create(name, chat_session_id)

    def list_active(self) -> List[ChatSession]:
        """List all active sessions sorted by last_active descending."""
        active = [s for s in self.sessions.values() if s.status == "active"]
        active.sort(key=lambda s: s.last_active, reverse=True)
        return active

    def update(self, name: str, parent_message_id: Optional[Union[str, int]] = None,
               add_context: Optional[str] = None):
        """Update session state after a message exchange.

        Args:
            name: Session name
            parent_message_id: New parent message ID for chaining
            add_context: Context identifier to add to injected list (e.g. "skill:design")
        """
        session = self.sessions.get(name)
        if not session:
            return
        if parent_message_id is not None:
            session.parent_message_id = parent_message_id
        if add_context and add_context not in session.injected_contexts:
            session.injected_contexts.append(add_context)
        session.message_count += 1
        session.last_active = time.time()
        session.system_prompt_sent = True
        self.save()

    def close(self, name: str) -> bool:
        """Close a session. Returns True if found and closed."""
        if name in self.sessions:
            self.sessions[name].status = "closed"
            self.save()
            return True
        return False

    def close_all(self) -> int:
        """Close all active sessions. Returns count of sessions closed."""
        count = 0
        for session in self.sessions.values():
            if session.status == "active":
                session.status = "closed"
                count += 1
        if count > 0:
            self.save()
        return count

    def cleanup_old(self, max_age_hours: int = 24):
        """Expire sessions older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        changed = False
        for session in self.sessions.values():
            if session.status == "active" and session.last_active < cutoff:
                session.status = "expired"
                changed = True
        if changed:
            self.save()

    def list_by_mode(self, mode: str) -> List[ChatSession]:
        """List active sessions filtered by mode namespace."""
        return [
            s for s in self.sessions.values()
            if s.status == "active" and s.mode == mode
        ]

    def get_session_digest(self, name: str) -> Optional[dict]:
        """Return a compact digest of a session for routing decisions."""
        session = self.get(name)
        if not session:
            return None
        return {
            "name": session.name,
            "mode": session.mode,
            "topic": session.topic,
            "summary": session.summary,
            "messages": session.message_count,
            "skills": [c.split(":", 1)[1] for c in session.injected_contexts if c.startswith("skill:")],
            "contexts": session.injected_contexts,
            "last_active": time.strftime("%H:%M", time.localtime(session.last_active)),
            "tokens_invested": session.system_prompt_tokens + session.total_injected_tokens,
        }

    def update_summary(self, name: str, topic: str = "", summary: str = ""):
        """Update a session's summary and topic."""
        session = self.sessions.get(name)
        if not session:
            return
        if topic:
            session.topic = topic
        if summary:
            session.summary = summary
            session.summary_updated_at = time.time()
        self.save()

    def summary(self) -> dict:
        """Return a summary of all sessions for JSON output."""
        active = self.list_active()
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len(active),
            "sessions": [
                {
                    "name": s.name,
                    "mode": s.mode,
                    "topic": s.topic or "",
                    "summary": s.summary or "",
                    "messages": s.message_count,
                    "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(s.created_at)),
                    "last_active": time.strftime("%Y-%m-%d %H:%M", time.localtime(s.last_active)),
                    "system_sent": s.system_prompt_sent,
                    "skills": [c.split(":", 1)[1] for c in s.injected_contexts if c.startswith("skill:")],
                    "tokens_invested": s.system_prompt_tokens + s.total_injected_tokens,
                }
                for s in active
            ],
        }
