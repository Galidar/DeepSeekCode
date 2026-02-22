"""Session namespace management for mode isolation.

Each operation mode gets its own namespace prefix to prevent
cross-contamination between sessions:

    chat:       Interactive mode chats (chat:Chat-1, chat:Chat-2)
    oneshot     One-shot queries (oneshot or oneshot:<topic>)
    delegate:   Delegation tasks (delegate:<task-slug>)
    converse:   Multi-turn conversations (converse:<topic>)
    quantum:    Quantum dual sessions (quantum:<task-slug>:A, quantum:<task-slug>:B)
    multi-step: Multi-step plan sessions (multi-step:<plan-id>:<step-id>)
"""

import re
import math
from typing import Tuple, Optional

VALID_MODES = {"chat", "oneshot", "delegate", "converse", "quantum", "multi-step"}


def build_session_name(mode: str, identifier: str = "", sub_id: str = "") -> str:
    """Build a namespaced session name.

    Examples:
        build_session_name("delegate", "auth-module") -> "delegate:auth-module"
        build_session_name("quantum", "game-engine", "A") -> "quantum:game-engine:A"
        build_session_name("oneshot") -> "oneshot"
        build_session_name("chat", "Chat-1") -> "chat:Chat-1"
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Valid: {VALID_MODES}")

    parts = [mode]
    if identifier:
        parts.append(identifier)
    if sub_id:
        parts.append(sub_id)

    return ":".join(parts)


def parse_session_name(name: str) -> Tuple[str, str, str]:
    """Parse a namespaced session name into (mode, identifier, sub_id).

    Examples:
        parse_session_name("delegate:auth-module") -> ("delegate", "auth-module", "")
        parse_session_name("quantum:game:A") -> ("quantum", "game", "A")
        parse_session_name("oneshot") -> ("oneshot", "", "")
        parse_session_name("chat:Chat-1") -> ("chat", "Chat-1", "")
    """
    parts = name.split(":", 2)
    mode = parts[0] if parts else ""
    identifier = parts[1] if len(parts) > 1 else ""
    sub_id = parts[2] if len(parts) > 2 else ""
    return mode, identifier, sub_id


def slugify(text: str, max_len: int = 30) -> str:
    """Convert a task description to a URL-safe slug for session naming.

    Examples:
        slugify("create login endpoint with JWT") -> "create-login-endpoint-with-jwt"
        slugify("implement UI for auth module!!! YES") -> "implement-ui-for-auth-module-yes"
    """
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower().strip())
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Truncate at word boundary
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit('-', 1)[0]
    return slug or "unnamed"


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string (~3.5 chars per token)."""
    if not text:
        return 0
    return math.ceil(len(text) / 3.5)
