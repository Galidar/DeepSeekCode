"""Clasificador inteligente de tareas para DeepSeek Code.

Analiza el mensaje del usuario y determina su complejidad,
permitiendo que el sistema adapte prompts, skills y memoria
de forma proporcional a la tarea real.

Niveles:
    CHAT (0)        — Saludos, charla casual. Prompt minimo.
    SIMPLE (1)      — Preguntas conceptuales. Sin skills.
    CODE_SIMPLE (2) — Tareas de codigo pequenas. Skills limitadas.
    CODE_COMPLEX (3)— Sistemas, arquitectura. Skills completas.
    DELEGATION (4)  — Modo delegacion explicita. Todo habilitado.
"""

import re
from enum import IntEnum
from typing import Set


class TaskLevel(IntEnum):
    """Niveles de complejidad de tarea."""
    CHAT = 0
    SIMPLE = 1
    CODE_SIMPLE = 2
    CODE_COMPLEX = 3
    DELEGATION = 4


# --- Patrones de deteccion ---

CHAT_PATTERNS: Set[str] = {
    "hola", "hey", "hello", "hi", "buenas", "buenos dias",
    "buenas tardes", "buenas noches", "que tal", "como estas",
    "como andas", "que onda", "gracias", "muchas gracias",
    "thanks", "thank you", "adios", "chao", "bye", "nos vemos",
    "ok", "vale", "perfecto", "genial", "listo", "entendido",
    "si", "no", "claro", "dale", "de acuerdo",
}

CODE_INDICATORS: Set[str] = {
    # Acciones de codigo
    "crea", "crear", "implementa", "implementar", "programa", "programar",
    "arregla", "arreglar", "fix", "corrige", "corregir", "modifica",
    "modificar", "agrega", "agregar", "add", "elimina", "refactoriza",
    "optimiza", "escribe", "escribir", "genera", "generar", "build",
    # Conceptos de codigo
    "funcion", "function", "clase", "class", "variable", "metodo",
    "method", "archivo", "file", "modulo", "module", "componente",
    "endpoint", "api", "ruta", "route", "test", "debug",
    # Lenguajes
    "javascript", "python", "typescript", "html", "css", "sql",
    "react", "node", "express", "canvas",
}

COMPLEXITY_INDICATORS: Set[str] = {
    # Escala
    "sistema", "system", "arquitectura", "architecture", "patron",
    "pattern", "modular", "framework", "pipeline", "workflow",
    # Multi-componente
    "servidor", "server", "cliente", "client", "base de datos",
    "database", "autenticacion", "authentication", "deploy",
    # Alcance grande
    "completo", "full", "entero", "proyecto", "project",
    "aplicacion", "application", "juego", "game",
    "refactorizar todo", "migrar", "migrate",
}

QUESTION_PATTERNS = re.compile(
    r'^(que|como|por que|cuando|donde|cual|cuanto|what|how|why|when|where|which)\b',
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Normaliza texto para comparacion."""
    text = text.lower().strip()
    replacements = {
        'a\u0301': 'a', 'e\u0301': 'e', 'i\u0301': 'i', 'o\u0301': 'o', 'u\u0301': 'u',
        '\u00e1': 'a', '\u00e9': 'e', '\u00ed': 'i', '\u00f3': 'o', '\u00fa': 'u',
        '\u00f1': 'n', '\u00fc': 'u',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _count_matches(text: str, patterns: Set[str]) -> int:
    """Cuenta cuantos patrones aparecen en el texto."""
    count = 0
    for pattern in patterns:
        if pattern in text:
            count += 1
    return count


def classify_task(message: str, is_delegation: bool = False) -> TaskLevel:
    """Clasifica un mensaje en su nivel de complejidad.

    Usa heuristicas basadas en patrones, no LLM.
    Sesgo conservador: en caso de duda, sube un nivel.

    Args:
        message: Mensaje del usuario
        is_delegation: True si viene de --delegate/--quantum

    Returns:
        TaskLevel apropiado para el mensaje
    """
    if is_delegation:
        return TaskLevel.DELEGATION

    if not message or not message.strip():
        return TaskLevel.CHAT

    normalized = _normalize(message)
    words = normalized.split()
    word_count = len(words)

    # --- Nivel 0: Chat ---
    # Mensajes cortos que son saludos, agradecimientos, confirmaciones
    if word_count <= 5:
        # Verificar si es un saludo/despedida exacto
        clean = re.sub(r'[!?.,;:\s]+', ' ', normalized).strip()
        if clean in CHAT_PATTERNS or any(p in clean for p in CHAT_PATTERNS):
            return TaskLevel.CHAT

    # Mensajes de 1-3 palabras sin indicadores de codigo → chat
    if word_count <= 3 and _count_matches(normalized, CODE_INDICATORS) == 0:
        return TaskLevel.CHAT

    # --- Nivel 3: Code Complex ---
    # Detectar primero (antes de code_simple) para no sub-clasificar
    complexity_score = _count_matches(normalized, COMPLEXITY_INDICATORS)
    code_score = _count_matches(normalized, CODE_INDICATORS)

    if complexity_score >= 2:
        return TaskLevel.CODE_COMPLEX
    if complexity_score >= 1 and code_score >= 2:
        return TaskLevel.CODE_COMPLEX
    if word_count > 50 and code_score >= 1:
        return TaskLevel.CODE_COMPLEX

    # --- Nivel 2: Code Simple ---
    # Requiere al menos 2 indicadores de codigo para evitar falsos positivos
    # (1 solo indicador como "file" o "test" no justifica inyectar skills)
    if code_score >= 2:
        return TaskLevel.CODE_SIMPLE

    # --- Nivel 1: Simple ---
    # Preguntas conceptuales o mensajes con 1 solo indicador de codigo
    if QUESTION_PATTERNS.match(normalized):
        return TaskLevel.SIMPLE

    if code_score == 1:
        return TaskLevel.SIMPLE

    # Mensajes medianos sin indicadores claros → sesgo conservador → SIMPLE
    if word_count > 5:
        return TaskLevel.SIMPLE

    return TaskLevel.CHAT
