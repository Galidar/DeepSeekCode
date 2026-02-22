"""Chunking inteligente de templates grandes para DeepSeek V3.2.

DeepSeek documenta que la precision degrada con contextos muy grandes.
Mejor 2-5K tokens relevantes que 100K de ruido. Este modulo divide
templates >30K tokens en chunks logicos por TODOs o por archivos,
cada uno con contexto de los otros chunks.

Uso:
    if should_chunk(template, threshold):
        chunks = chunk_by_todos(template)
        for i, chunk in enumerate(chunks):
            prompt = build_chunk_prompt(chunk, len(chunks), i)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class TemplateChunk:
    """Un fragmento logico de un template grande."""
    content: str
    todo_names: List[str] = field(default_factory=list)
    label: str = ""
    start_line: int = 0
    end_line: int = 0

    @property
    def estimated_tokens(self) -> int:
        return len(self.content) // 4


def estimate_tokens(text: str) -> int:
    """Estimacion rapida: ~4 chars por token."""
    return len(text) // 4


def should_chunk(template: str, threshold_tokens: int = 30000) -> bool:
    """Determina si un template necesita chunking.

    Args:
        template: Contenido del template completo
        threshold_tokens: Umbral en tokens (default: 30K)

    Returns:
        True si el template excede el umbral
    """
    return estimate_tokens(template) > threshold_tokens


def chunk_by_todos(
    template: str,
    max_tokens_per_chunk: int = 5000,
) -> List[TemplateChunk]:
    """Divide template en chunks basados en bloques TODO.

    Cada chunk contiene 1+ TODOs adyacentes hasta el limite de tokens.
    Si no hay TODOs, cae a chunk_by_lines().

    Args:
        template: Template completo
        max_tokens_per_chunk: Maximo tokens por chunk

    Returns:
        Lista de TemplateChunk
    """
    # Encontrar posiciones de todos los TODO markers
    todo_pattern = re.compile(
        r'^.*(?:TODO\s+[\dA-Za-z]+\s*:|/\*\s*TODO:).*$',
        re.MULTILINE,
    )
    matches = list(todo_pattern.finditer(template))

    if not matches:
        return chunk_by_lines(template, max_tokens_per_chunk)

    lines = template.split('\n')
    chunks = []
    current_lines = []
    current_todos = []
    current_start = 0

    # Mapear posiciones de match a numeros de linea
    todo_line_nums = set()
    for m in matches:
        line_num = template[:m.start()].count('\n')
        todo_line_nums.add(line_num)

    for i, line in enumerate(lines):
        is_todo_boundary = i in todo_line_nums and current_lines

        # Si encontramos un nuevo TODO y el chunk actual es grande, cortar
        if is_todo_boundary:
            current_text = '\n'.join(current_lines)
            if estimate_tokens(current_text) >= max_tokens_per_chunk:
                chunks.append(TemplateChunk(
                    content=current_text,
                    todo_names=list(current_todos),
                    label=f"TODOs: {', '.join(current_todos)}" if current_todos else "",
                    start_line=current_start,
                    end_line=i - 1,
                ))
                current_lines = []
                current_todos = []
                current_start = i

        current_lines.append(line)

        # Extraer nombre del TODO si esta linea es un marker
        if i in todo_line_nums:
            name_match = re.search(r'TODO\s+[\dA-Za-z]+\s*:\s*(\w+)', line)
            if not name_match:
                name_match = re.search(r'/\*\s*TODO:\s*(\w+)', line)
            if name_match:
                current_todos.append(name_match.group(1))

    # Ultimo chunk
    if current_lines:
        chunks.append(TemplateChunk(
            content='\n'.join(current_lines),
            todo_names=list(current_todos),
            label=f"TODOs: {', '.join(current_todos)}" if current_todos else "final",
            start_line=current_start,
            end_line=len(lines) - 1,
        ))

    return chunks


def chunk_by_lines(
    template: str,
    max_tokens_per_chunk: int = 5000,
) -> List[TemplateChunk]:
    """Fallback: divide por lineas cuando no hay TODO markers.

    Args:
        template: Template completo
        max_tokens_per_chunk: Maximo tokens por chunk

    Returns:
        Lista de TemplateChunk
    """
    lines = template.split('\n')
    max_lines = max(10, (max_tokens_per_chunk * 4) // 80)  # ~80 chars/linea
    chunks = []

    for start in range(0, len(lines), max_lines):
        end = min(start + max_lines, len(lines))
        content = '\n'.join(lines[start:end])
        chunks.append(TemplateChunk(
            content=content,
            label=f"lineas {start+1}-{end}",
            start_line=start,
            end_line=end - 1,
        ))

    return chunks


def build_chunk_prompt(
    chunk: TemplateChunk,
    total_chunks: int,
    chunk_index: int,
    task: str = "",
    previous_output: str = "",
) -> str:
    """Construye prompt para un chunk individual con contexto.

    Cada chunk sabe que es parte de un todo mas grande y que
    otros chunks existen. Si hay output previo, se incluye como
    contexto para continuidad.

    Args:
        chunk: El chunk actual
        total_chunks: Numero total de chunks
        chunk_index: Indice 0-based del chunk actual
        task: Descripcion de la tarea
        previous_output: Output del chunk anterior (para continuidad)

    Returns:
        Prompt ensamblado
    """
    parts = []

    # Header de contexto
    parts.append(
        f"[CHUNK {chunk_index + 1}/{total_chunks}] "
        f"{chunk.label}"
    )

    if chunk_index > 0:
        parts.append(
            "IMPORTANTE: Este es un chunk de continuacion. "
            "El codigo anterior ya fue generado. "
            "Solo implementa los TODOs de ESTE chunk."
        )

    if previous_output:
        # Incluir solo las ultimas lineas del output anterior como contexto
        prev_lines = previous_output.strip().split('\n')
        context_lines = prev_lines[-20:] if len(prev_lines) > 20 else prev_lines
        parts.append(
            f"CONTEXTO (ultimas lineas del chunk anterior):\n"
            f"```\n{chr(10).join(context_lines)}\n```"
        )

    if task:
        parts.append(f"TAREA: {task}")

    parts.append(f"TEMPLATE (chunk {chunk_index + 1}):\n```\n{chunk.content}\n```")

    if chunk.todo_names:
        parts.append(
            f"TODOs a implementar en este chunk: {', '.join(chunk.todo_names)}"
        )

    return '\n\n'.join(parts)
