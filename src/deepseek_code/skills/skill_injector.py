"""Inyeccion automatica de skills relevantes en el contexto de DeepSeek.

Analiza el mensaje del usuario y selecciona skills de conocimiento relevantes
para inyectarlas en el system prompt, mejorando la calidad del codigo generado.

Sistema adaptivo con 2 modos:
- Negociado: DeepSeek elige sus propias skills del catalogo (preferido)
- Heuristico: keyword matching como fallback (siempre disponible)

Budgets escalan con complejidad: chat=0, simple=0, code=10-40K, delegation=80K.
"""

import re
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from .loader import SkillLoader, KnowledgeSkill
from .skill_constants import (
    SKILL_KEYWORD_MAP, GAME_KEYWORDS, GAME_SKILLS, CORE_SKILLS,
    DELEGATE_TOKEN_BUDGET, INTERACTIVE_TOKEN_BUDGET,
    ADAPTIVE_BUDGETS, ERROR_REFERENCE_SKILL,
)


def _normalize_text(text: str) -> str:
    """Normaliza texto para busqueda de keywords (minusculas, sin acentos)."""
    text = text.lower()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ñ': 'n', 'ü': 'u',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _estimate_tokens(text: str) -> int:
    """Estima tokens de un texto (~4 chars por token)."""
    return len(text) // 4


def detect_relevant_skills(
    message: str,
    max_skills: int = 5,
    exclude: List[str] = None
) -> List[str]:
    """Detecta que skills son relevantes basandose en el mensaje del usuario.

    Args:
        message: Mensaje del usuario
        max_skills: Maximo de skills a retornar
        exclude: Skills a excluir (ej: core skills ya cargados)

    Returns:
        Lista de nombres de skills ordenados por relevancia
    """
    normalized = _normalize_text(message)
    scores: Dict[str, int] = {}
    exclude_set = set(exclude or [])

    for skill_name, keywords in SKILL_KEYWORD_MAP.items():
        if skill_name in exclude_set:
            continue
        score = 0
        for kw in keywords:
            kw_norm = _normalize_text(kw)
            if kw_norm in normalized:
                score += len(kw_norm)
        if score > 0:
            scores[skill_name] = score

    # Bonus por contexto de juegos
    is_game_context = any(
        _normalize_text(kw) in normalized for kw in GAME_KEYWORDS
    )
    if is_game_context:
        for skill_name in GAME_SKILLS:
            if skill_name not in exclude_set:
                scores[skill_name] = scores.get(skill_name, 0) + 20

    sorted_skills = sorted(scores.items(), key=lambda x: -x[1])
    return [name for name, _ in sorted_skills[:max_skills]]


def load_skill_contents(
    skills_dir: str,
    skill_names: List[str]
) -> List[Tuple[str, str, int]]:
    """Carga el contenido de las skills seleccionadas.

    Returns:
        Lista de (nombre, contenido, tokens_estimados)
    """
    loader = SkillLoader(skills_dir)
    results = []
    for name in skill_names:
        skill = loader.load_one(name)
        if skill and isinstance(skill, KnowledgeSkill):
            estimated_tokens = _estimate_tokens(skill.content)
            results.append((skill.name, skill.content, estimated_tokens))
    return results


def _load_skills_with_budget(
    skills_dir: str,
    skill_names: List[str],
    token_budget: int,
    header: str = ""
) -> Tuple[str, int]:
    """Carga skills respetando un presupuesto de tokens.

    No trunca skills individuales — respeta el budget global.

    Returns:
        (contexto_formateado, tokens_usados)
    """
    if not skill_names:
        return "", 0

    loaded = load_skill_contents(skills_dir, skill_names)
    if not loaded:
        return "", 0

    parts = []
    if header:
        parts.append(header)
    total_tokens = _estimate_tokens(header)

    for name, content, tokens in loaded:
        if total_tokens + tokens > token_budget:
            # Si es la primera skill y excede, incluir lo que quepa
            if not parts or (len(parts) == 1 and header):
                remaining_chars = (token_budget - total_tokens) * 4
                if remaining_chars > 500:
                    content = content[:remaining_chars]
                    tokens = remaining_chars // 4
                else:
                    break
            else:
                break
        parts.append(f"\n--- {name} ---\n{content}\n")
        total_tokens += tokens

    return "".join(parts), total_tokens


def build_skills_context(
    skills_dir: str,
    message: str,
    mode: str = "web",
    max_skills: int = 5,
    task_level: str = "code_complex",
) -> str:
    """Construye el bloque de contexto de skills para modo interactivo.

    Adaptivo: no inyecta skills para chat o preguntas simples.

    Args:
        skills_dir: Directorio de skills
        message: Mensaje del usuario (para detectar relevancia)
        mode: "web" o "api" (afecta limite de tokens)
        max_skills: Maximo de skills a inyectar
        task_level: Nivel de tarea (de TaskLevel.name.lower())
    """
    if not skills_dir or not Path(skills_dir).exists():
        return ""

    # Adaptivo: chat y simple no necesitan skills
    budget = ADAPTIVE_BUDGETS.get(task_level)
    if budget and budget["total"] == 0:
        return ""

    relevant = detect_relevant_skills(message, max_skills)
    if not relevant:
        return ""

    # Usar budget adaptativo si disponible, sino fallback a interactive
    if budget:
        max_tokens = budget["domain"]
    else:
        max_tokens = INTERACTIVE_TOKEN_BUDGET.get(mode, 12000)

    context, used = _load_skills_with_budget(
        skills_dir, relevant, max_tokens,
        header="\n\n== CONOCIMIENTO ESPECIALIZADO (skills auto-inyectadas) ==\n",
    )

    if not context:
        return ""

    return context + "\n== FIN SKILLS ==\n"


def build_delegate_skills_context(
    skills_dir: str,
    task_description: str,
    max_skills: int = 8,
    task_level: str = "delegation",
    has_recurring_errors: bool = False,
) -> str:
    """Construye contexto de skills para modo delegacion con inyeccion adaptiva.

    Ya no inyecta Core Skills ciegamente. Solo inyecta:
    - Domain skills relevantes a la tarea (Tier 2)
    - Specialist skills si hay espacio (Tier 3)
    - common-errors-reference solo si hay errores recurrentes

    Args:
        skills_dir: Directorio de skills
        task_description: Descripcion de la tarea delegada
        max_skills: Maximo de skills de dominio (Tier 2+3)
        task_level: Nivel de tarea para budget adaptivo
        has_recurring_errors: Si SurgicalMemory reporta errores recurrentes
    """
    if not skills_dir or not Path(skills_dir).exists():
        return ""

    budget = ADAPTIVE_BUDGETS.get(task_level, DELEGATE_TOKEN_BUDGET)
    if budget["total"] == 0:
        return ""

    total_used = 0
    all_parts = []

    # --- Error reference condicional (solo si hay errores recurrentes) ---
    if has_recurring_errors:
        err_context, err_tokens = _load_skills_with_budget(
            skills_dir, [ERROR_REFERENCE_SKILL], 5000,
            header="\n\n== ERRORES FRECUENTES (de tu historial) ==\n",
        )
        if err_context:
            all_parts.append(err_context)
            total_used += err_tokens

    # --- Domain Skills (por relevancia) ---
    relevant = detect_relevant_skills(
        task_description, max_skills, exclude=CORE_SKILLS
    )

    if relevant:
        domain_budget = min(budget["domain"], budget["total"] - total_used)
        domain_context, domain_tokens = _load_skills_with_budget(
            skills_dir, relevant, domain_budget,
            header="\n\n== CONOCIMIENTO DE DOMINIO (por relevancia) ==\n",
        )
        if domain_context:
            all_parts.append(domain_context)
            total_used += domain_tokens

    # --- Specialist overflow (si hay espacio) ---
    remaining = budget["total"] - total_used
    if remaining > 2000 and relevant:
        extra = detect_relevant_skills(
            task_description, max_skills + 5,
            exclude=CORE_SKILLS + relevant
        )
        if extra:
            spec_budget = min(budget.get("specialist", 20000), remaining)
            spec_context, spec_tokens = _load_skills_with_budget(
                skills_dir, extra[:3], spec_budget,
                header="\n== REFERENCIA COMPLEMENTARIA ==\n",
            )
            if spec_context:
                all_parts.append(spec_context)

    if not all_parts:
        return ""

    return "".join(all_parts) + "\n== FIN CONOCIMIENTO ==\n"
