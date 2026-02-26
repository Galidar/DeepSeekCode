"""Central orchestrator for session-based token-efficient messaging.

Replaces the scattered enriched_system pattern where each mode (delegate,
converse, quantum) builds a monolithic prompt from base + skills + surgical
+ global. Instead, the orchestrator decides:

1. Whether system prompt needs to be sent (new session only)
2. Which skills/memory/errors need injection (only new ones)
3. What the clean user message should be

Token savings: On session reuse, reduces ~92K tokens to ~200 tokens.
"""

import sys
import math
from typing import Optional, List, Dict, Callable, Tuple

from .session_store import SessionStore
from .session_namespace import build_session_name, slugify, estimate_tokens


class SessionOrchestrator:
    """Decides what to inject into a session based on its current state.

    Centralizes the detection of skills, surgical memory, global memory,
    and knowledge transfers as separate Phase 2 injections, each tracked
    independently to avoid re-sending.
    """

    def __init__(
        self,
        session_store: SessionStore,
        skills_dir: str = "",
        appdata_dir: str = "",
    ):
        self.store = session_store
        self.skills_dir = skills_dir
        self.appdata_dir = appdata_dir

    def prepare_session_call(
        self,
        mode: str,
        identifier: str,
        user_message: str,
        system_prompt_builder: Optional[Callable] = None,
        base_system_prompt: Optional[str] = None,
        task_text: str = "",
        template_path: Optional[str] = None,
        context_path: Optional[str] = None,
        project_context_path: Optional[str] = None,
        extra_injections: Optional[List[Dict]] = None,
    ) -> dict:
        """Prepare everything needed for a chat_in_session call.

        This is the main entry point. Each mode calls this instead of
        building enriched_system manually.

        Args:
            mode: Session mode (delegate, converse, quantum, etc.)
            identifier: Task slug or session identifier
            user_message: The user's message
            system_prompt_builder: Callable that returns system prompt string
            base_system_prompt: Pre-built system prompt (alternative to builder)
            task_text: Extended task text for skill detection
            template_path: Path to template (for surgical memory)
            context_path: Path to context file (for surgical memory)
            project_context_path: Path to CLAUDE.md (for surgical memory)
            extra_injections: Additional injections to include

        Returns:
            dict with: session_name, system_prompt, pending_injections,
                       user_message, surgical_store, global_store
        """
        session_name = build_session_name(mode, identifier)
        session = self.store.get(session_name)

        # System prompt: only build if session is new
        system_prompt = None
        if not session or not session.system_prompt_sent:
            if system_prompt_builder:
                system_prompt = system_prompt_builder()
            elif base_system_prompt:
                system_prompt = base_system_prompt

        # Detect all pending injections
        detection_text = task_text or user_message
        pending, surgical_store, global_store = self._detect_all_injections(
            session, detection_text,
            template_path=template_path,
            context_path=context_path,
            project_context_path=project_context_path,
        )

        # Add any extra injections (e.g., knowledge transfers)
        if extra_injections:
            already = set(session.injected_contexts) if session else set()
            for inj in extra_injections:
                ctx_id = f"{inj['type']}:{inj['name']}"
                if ctx_id not in already:
                    pending.append(inj)

        # Track estimated token cost of system prompt
        if system_prompt and (not session or not session.system_prompt_sent):
            est_tokens = estimate_tokens(system_prompt)
            # Will be stored after session creation in session_chat.py
            # We pass it in the result for the caller to use
        else:
            est_tokens = 0

        return {
            "session_name": session_name,
            "mode": mode,
            "system_prompt": system_prompt,
            "system_prompt_tokens": est_tokens,
            "pending_injections": pending,
            "user_message": user_message,
            "surgical_store": surgical_store,
            "global_store": global_store,
        }

    def _detect_all_injections(
        self,
        session,
        task_text: str,
        template_path: Optional[str] = None,
        context_path: Optional[str] = None,
        project_context_path: Optional[str] = None,
    ) -> Tuple[List[Dict], object, object]:
        """Detect skills + surgical + global as separate injections.

        Only returns injections not yet sent to this session.
        Each injection: {"type": "skill"|"memory"|"global", "name": ..., "content": ...}

        Returns:
            Tuple of (injections_list, surgical_store, global_store)
        """
        already = set(session.injected_contexts) if session else set()
        injections = []
        surgical_store = None
        global_store = None

        # 1. Skills (via TF-IDF semantic detection)
        injections.extend(self._detect_skill_injections(task_text, already))

        # 2. Surgical memory briefing (per-project)
        surgical_inj, surgical_store = self._detect_surgical_injection(
            task_text, already,
            template_path=template_path,
            context_path=context_path,
            project_context_path=project_context_path,
        )
        if surgical_inj:
            injections.append(surgical_inj)

        # 3. Global memory briefing (cross-project)
        global_inj, global_store = self._detect_global_injection(
            task_text, already,
        )
        if global_inj:
            injections.append(global_inj)

        return injections, surgical_store, global_store

    def _detect_skill_injections(self, task_text: str, already: set) -> List[Dict]:
        """Detect relevant skills that haven't been injected yet."""
        if not self.skills_dir:
            return []

        try:
            from ..skills.skill_injector import detect_relevant_skills, load_skill_contents
            from ..client.task_classifier import classify_task, TaskLevel

            # Respetar clasificacion: no inyectar skills para chat/simple
            level = classify_task(task_text)
            if level <= TaskLevel.SIMPLE:
                return []
            max_sk = 2 if level == TaskLevel.CODE_SIMPLE else 5
            relevant = detect_relevant_skills(task_text, max_skills=max_sk)
            if not relevant:
                return []

            loaded = load_skill_contents(self.skills_dir, relevant)
            injections = []
            for name, content, tokens in loaded:
                ctx_id = f"skill:{name}"
                if ctx_id not in already:
                    injections.append({
                        "type": "skill",
                        "name": name,
                        "content": content,
                    })
            return injections
        except Exception as e:
            print(f"  [orchestrator] Error detecting skills: {e}", file=sys.stderr)
            return []

    def _detect_surgical_injection(
        self, task_text: str, already: set, **kwargs,
    ) -> Tuple[Optional[Dict], object]:
        """Detect surgical memory briefing if not yet injected."""
        ctx_id = "memory:surgical"
        if ctx_id in already or not self.appdata_dir:
            return None, None

        try:
            from ..surgical.integration import pre_delegation
            briefing, store = pre_delegation(
                self.appdata_dir, task_text,
                template_path=kwargs.get("template_path"),
                context_path=kwargs.get("context_path"),
                project_context_path=kwargs.get("project_context_path"),
            )
            if briefing and briefing.strip():
                return {
                    "type": "memory",
                    "name": "surgical-project",
                    "content": briefing,
                }, store
            return None, store
        except Exception as e:
            print(f"  [orchestrator] Error detecting surgical memory: {e}", file=sys.stderr)
            return None, None

    def _detect_global_injection(
        self, task_text: str, already: set,
    ) -> Tuple[Optional[Dict], object]:
        """Detect global memory briefing if not yet injected."""
        ctx_id = "memory:global"
        if ctx_id in already or not self.appdata_dir:
            return None, None

        try:
            from ..global_memory.global_integration import global_pre_delegation
            briefing, store = global_pre_delegation(self.appdata_dir, task_text)
            if briefing and briefing.strip():
                return {
                    "type": "global",
                    "name": "developer-profile",
                    "content": briefing,
                }, store
            return None, store
        except Exception as e:
            print(f"  [orchestrator] Error detecting global memory: {e}", file=sys.stderr)
            return None, None

    def get_routing_digest(self) -> dict:
        """Get a compact digest of all active sessions for routing decisions.

        Claude uses this to decide which session to route messages to.
        """
        active = self.store.list_active()
        sessions = []
        for s in active:
            sessions.append({
                "name": s.name,
                "mode": s.mode,
                "topic": s.topic or s.name,
                "summary": s.summary or f"{s.message_count} mensajes",
                "messages": s.message_count,
                "skills": [c.split(":", 1)[1] for c in s.injected_contexts
                           if c.startswith("skill:")],
                "last_active": s.last_active,
                "tokens_invested": s.system_prompt_tokens + s.total_injected_tokens,
            })

        return {
            "active_sessions": sessions,
            "total_active": len(sessions),
        }
