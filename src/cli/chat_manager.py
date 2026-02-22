"""Gestiona chats nombrados en el modo interactivo.

Cada chat es una sesion persistente independiente en DeepSeek.
El usuario puede crear, cambiar, cerrar y listar chats.

Comandos:
    /chat           Ver chat actual
    /chats          Listar todos los chats activos
    /new [nombre]   Crear nuevo chat
    /switch <nombre> Cambiar a otro chat
    /close [nombre] Cerrar chat actual o uno especifico
"""

import time
from deepseek_code.client.session_chat import get_session_store


class ChatManager:
    """Manages named chats for the interactive mode."""

    PREFIX = "chat:"  # Prefix to namespace interactive chats

    def __init__(self, client):
        self.client = client
        self.current = None
        self._counter = 0

    def _store(self):
        return get_session_store()

    def _full_name(self, name: str) -> str:
        """Add prefix to distinguish interactive chats from other sessions."""
        if name.startswith(self.PREFIX):
            return name
        return f"{self.PREFIX}{name}"

    def _display_name(self, full_name: str) -> str:
        """Strip prefix for display."""
        if full_name.startswith(self.PREFIX):
            return full_name[len(self.PREFIX):]
        return full_name

    def init_or_resume(self):
        """Initialize: resume last active chat or create a new one."""
        store = self._store()
        store.cleanup_old(max_age_hours=72)

        # Find the most recently active interactive chat
        active = [
            s for s in store.list_active()
            if s.name.startswith(self.PREFIX)
        ]

        if active:
            # Resume the most recent one
            self.current = self._display_name(active[0].name)
        else:
            # Create first chat
            self.current = self._generate_name()

        self.client.default_session_name = self._full_name(self.current)

    def _generate_name(self) -> str:
        """Generate a sequential chat name."""
        store = self._store()
        # Find highest existing number
        max_num = 0
        for s in store.sessions.values():
            if s.name.startswith(self.PREFIX):
                suffix = s.name[len(self.PREFIX):]
                if suffix.startswith("Chat-"):
                    try:
                        num = int(suffix[5:])
                        max_num = max(max_num, num)
                    except ValueError:
                        pass
        return f"Chat-{max_num + 1}"

    def new_chat(self, name: str = None):
        """Create a new chat and switch to it."""
        self.current = name or self._generate_name()
        self.client.default_session_name = self._full_name(self.current)

    def switch(self, name: str) -> bool:
        """Switch to an existing chat. Returns True if found."""
        store = self._store()
        full = self._full_name(name)
        session = store.get(full)
        if session:
            self.current = name
            self.client.default_session_name = full
            return True
        return False

    def close_chat(self, name: str = None) -> str:
        """Close a chat. Returns the name of closed chat, or None."""
        store = self._store()
        target = name or self.current
        full = self._full_name(target)

        if not store.close(full):
            return None

        closed_name = target

        # If we closed the current chat, switch to another or create new
        if target == self.current:
            active = [
                s for s in store.list_active()
                if s.name.startswith(self.PREFIX)
            ]
            if active:
                self.current = self._display_name(active[0].name)
            else:
                self.current = self._generate_name()
            self.client.default_session_name = self._full_name(self.current)

        return closed_name

    def list_all(self) -> list:
        """List all active interactive chats."""
        store = self._store()
        store.cleanup_old(max_age_hours=72)
        active = [
            s for s in store.list_active()
            if s.name.startswith(self.PREFIX)
        ]
        return [
            {
                "name": self._display_name(s.name),
                "messages": s.message_count,
                "last_active": time.strftime("%H:%M", time.localtime(s.last_active)),
                "current": self._display_name(s.name) == self.current,
            }
            for s in active
        ]

    def info(self) -> dict:
        """Info about the current chat."""
        store = self._store()
        full = self._full_name(self.current)
        session = store.get(full)
        return {
            "name": self.current,
            "messages": session.message_count if session else 0,
            "system_sent": session.system_prompt_sent if session else False,
        }
