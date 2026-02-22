"""Herramienta para gestionar la memoria persistente del asistente.

Soporta categorias, busqueda por seccion, y limpieza automatica de resumenes viejos.
"""

import os
import re
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import Optional
from ..server.tool import BaseTool

# Limite de tamaño de memoria (5 MB — suficiente para sesiones largas)
MAX_MEMORY_BYTES = 5 * 1024 * 1024
# Maximo de resumenes automaticos antes de compactar
MAX_AUTO_SUMMARIES = 20


class MemoryTool(BaseTool):
    """Lee y actualiza el archivo de memoria persistente con soporte de categorias."""

    def __init__(self, memory_path: str):
        self.memory_path = Path(memory_path).expanduser().resolve()
        super().__init__(
            name="memory",
            description=(
                "Gestiona la memoria persistente del asistente (archivo Markdown). "
                "Acciones: read (leer todo o por categoria), append (añadir con categoria opcional), "
                "write (sobrescribir), search (buscar texto), compact (limpiar resumenes viejos), "
                "stats (ver estadisticas de la memoria). "
                "Categorias comunes: preferencias, proyectos, decisiones, errores, notas. "
                "Limite de 5MB."
            )
        )

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "append", "write", "search", "compact", "stats"],
                    "description": (
                        "'read': leer memoria (opcionalmente filtrar por categoria). "
                        "'append': añadir texto (opcionalmente con categoria). "
                        "'write': sobrescribir toda la memoria. "
                        "'search': buscar texto en la memoria. "
                        "'compact': compactar resumenes automaticos viejos. "
                        "'stats': ver estadisticas de uso de la memoria."
                    )
                },
                "content": {
                    "type": "string",
                    "description": "Contenido a añadir o escribir (para 'append' o 'write')"
                },
                "category": {
                    "type": "string",
                    "description": "Categoria para organizar (ej: preferencias, proyectos, decisiones, errores)"
                },
                "search_query": {
                    "type": "string",
                    "description": "Texto a buscar en la memoria (solo para action='search')"
                }
            },
            "required": ["action"]
        }

    async def _read_memory(self) -> str:
        if not self.memory_path.exists():
            return ""
        async with aiofiles.open(self.memory_path, 'r', encoding='utf-8') as f:
            return await f.read()

    async def _write_memory(self, content: str):
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.memory_path, 'w', encoding='utf-8') as f:
            await f.write(content)

    def _extract_sections(self, content: str) -> dict:
        """Extrae secciones por encabezado ## del Markdown."""
        sections = {}
        current_header = "general"
        current_lines = []

        for line in content.splitlines():
            if line.startswith("## "):
                if current_lines:
                    sections.setdefault(current_header, []).extend(current_lines)
                current_header = line[3:].strip().lower()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.setdefault(current_header, []).extend(current_lines)
        return sections

    async def execute(self, action: str, content: Optional[str] = None,
                      category: Optional[str] = None, search_query: Optional[str] = None) -> str:
        try:
            if action == "read":
                return await self._action_read(category)
            elif action == "append":
                return await self._action_append(content, category)
            elif action == "write":
                return await self._action_write(content)
            elif action == "search":
                return await self._action_search(search_query)
            elif action == "compact":
                return await self._action_compact()
            elif action == "stats":
                return await self._action_stats()
            else:
                return f"Error: Accion no valida '{action}'. Usa: read, append, write, search, compact, stats."
        except Exception as e:
            return f"Error con la memoria: {str(e)}"

    async def _action_read(self, category: Optional[str]) -> str:
        memory = await self._read_memory()
        if not memory.strip():
            return "La memoria esta vacia. Usa 'append' para añadir informacion."

        size = len(memory.encode('utf-8'))

        if category:
            sections = self._extract_sections(memory)
            cat_lower = category.lower()
            # Buscar seccion que coincida parcialmente
            matches = {k: v for k, v in sections.items() if cat_lower in k}
            if matches:
                result = f"**Memoria — categoria '{category}'** ({size} bytes total):\n\n"
                for header, lines in matches.items():
                    content_text = "\n".join(lines).strip()
                    if content_text:
                        result += f"## {header}\n{content_text}\n\n"
                return result
            return f"No se encontro la categoria '{category}'. Categorias disponibles: {', '.join(sections.keys())}"

        return f"**Memoria completa** ({size:,} bytes):\n\n{memory}"

    async def _action_append(self, content: Optional[str], category: Optional[str]) -> str:
        if not content:
            return "Error: Se requiere 'content' para append."

        current_size = self.memory_path.stat().st_size if self.memory_path.exists() else 0
        new_content = ""

        if category:
            new_content = f"\n## {category.capitalize()}\n{content}\n"
        else:
            new_content = f"\n{content}\n"

        new_size = current_size + len(new_content.encode('utf-8'))
        if new_size > MAX_MEMORY_BYTES:
            return (f"Error: La memoria alcanzaria {new_size:,} bytes "
                    f"(limite {MAX_MEMORY_BYTES // (1024*1024)}MB). "
                    f"Usa 'compact' para limpiar resumenes viejos o 'write' para reemplazar.")

        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.memory_path, 'a', encoding='utf-8') as f:
            await f.write(new_content)

        cat_info = f" en categoria '{category}'" if category else ""
        return f"Añadido a la memoria{cat_info} ({len(content)} chars)"

    async def _action_write(self, content: Optional[str]) -> str:
        if content is None:
            return "Error: Se requiere 'content' para write."
        content_size = len(content.encode('utf-8'))
        if content_size > MAX_MEMORY_BYTES:
            return f"Error: El contenido ({content_size:,} bytes) excede el limite de {MAX_MEMORY_BYTES // (1024*1024)}MB."
        await self._write_memory(content)
        return f"Memoria sobrescrita ({content_size:,} bytes)"

    async def _action_search(self, search_query: Optional[str]) -> str:
        if not search_query:
            return "Error: Se requiere 'search_query' para search."
        memory = await self._read_memory()
        if not memory:
            return "No hay nada en la memoria para buscar."

        query_lower = search_query.lower()
        lines = memory.splitlines()
        matches = []
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Incluir contexto: 1 linea antes y despues
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                context = "\n".join(lines[start:end])
                matches.append((i + 1, context))

        if matches:
            shown = matches[:30]
            result = f"**{len(matches)} coincidencia(s) para '{search_query}':**\n\n"
            for line_num, context in shown:
                result += f"Linea {line_num}:\n```\n{context}\n```\n\n"
            if len(matches) > 30:
                result += f"... y {len(matches) - 30} mas."
            return result
        return f"No se encontro '{search_query}' en la memoria."

    async def _action_compact(self) -> str:
        """Compacta resumenes automaticos: mantiene solo los 3 mas recientes."""
        memory = await self._read_memory()
        if not memory:
            return "La memoria esta vacia, nada que compactar."

        # Separar resumenes automaticos del contenido manual
        lines = memory.splitlines()
        summaries = []
        manual_lines = []
        in_summary = False
        current_summary = []

        for line in lines:
            if line.startswith("## Resumen de conversacion ("):
                if current_summary and in_summary:
                    summaries.append("\n".join(current_summary))
                in_summary = True
                current_summary = [line]
            elif in_summary and line.startswith("## ") and not line.startswith("## Resumen de conversacion"):
                summaries.append("\n".join(current_summary))
                in_summary = False
                manual_lines.append(line)
            elif in_summary:
                current_summary.append(line)
            else:
                manual_lines.append(line)

        if current_summary and in_summary:
            summaries.append("\n".join(current_summary))

        if len(summaries) <= 3:
            return f"Solo hay {len(summaries)} resumenes, no es necesario compactar."

        # Mantener solo los 3 mas recientes
        kept = summaries[-3:]
        removed = len(summaries) - 3

        new_content = "\n".join(manual_lines).strip()
        if kept:
            new_content += "\n\n" + "\n\n".join(kept)
        new_content += "\n"

        old_size = len(memory.encode('utf-8'))
        await self._write_memory(new_content)
        new_size = len(new_content.encode('utf-8'))

        return (f"Compactado: {removed} resumenes eliminados, 3 conservados. "
                f"Tamaño: {old_size:,} → {new_size:,} bytes "
                f"({old_size - new_size:,} bytes liberados)")

    async def _action_stats(self) -> str:
        """Muestra estadisticas de la memoria."""
        memory = await self._read_memory()
        if not memory:
            return "La memoria esta vacia."

        size_bytes = len(memory.encode('utf-8'))
        size_pct = size_bytes * 100 / MAX_MEMORY_BYTES
        lines_count = len(memory.splitlines())
        sections = self._extract_sections(memory)
        summary_count = memory.count("## Resumen de conversacion")

        result = f"**Estadisticas de memoria:**\n\n"
        result += f"- Tamaño: {size_bytes:,} bytes ({size_pct:.1f}% del limite de {MAX_MEMORY_BYTES // (1024*1024)}MB)\n"
        result += f"- Lineas: {lines_count:,}\n"
        result += f"- Secciones: {len(sections)}\n"
        result += f"- Resumenes automaticos: {summary_count}\n\n"

        if sections:
            result += "**Categorias:**\n"
            for name, section_lines in sections.items():
                content_len = sum(len(l) for l in section_lines)
                result += f"  - {name}: {len(section_lines)} lineas ({content_len:,} chars)\n"

        return result
