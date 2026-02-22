"""Clase base para herramientas MCP"""

from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseTool(ABC):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.input_schema = self._build_schema()

    @abstractmethod
    def _build_schema(self) -> Dict[str, Any]:
        """Define el esquema JSON de entrada para la herramienta"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """Ejecuta la herramienta con los argumentos dados"""
        pass