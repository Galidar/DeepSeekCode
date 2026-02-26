"""Catalogo compacto de skills para negociacion AI-a-AI.

Genera un listado ligero (nombre + descripcion) de todas las skills
disponibles para que DeepSeek pueda decidir cuales necesita.
No carga el contenido completo — solo metadatos.

Flujo:
    1. Claude envia el catalogo (~2K tokens para ~49 skills)
    2. DeepSeek responde con los nombres que quiere
    3. Solo esas skills se cargan completas
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .loader import SkillLoader, KnowledgeSkill, SkillDefinition


# Cache global: se genera una vez y se reutiliza toda la sesion
_catalog_cache: Optional[str] = None
_catalog_entries: Optional[Dict[str, str]] = None  # name -> description


def _build_entries(skills_dir: str) -> Dict[str, str]:
    """Extrae nombre+descripcion de todas las skills sin cargar contenido.

    Returns:
        Dict {nombre: descripcion} de todas las skills disponibles
    """
    loader = SkillLoader(skills_dir)
    all_skills = loader.load_all()
    entries = {}

    for name, skill in sorted(all_skills.items()):
        if isinstance(skill, KnowledgeSkill):
            desc = skill.description or "(knowledge skill)"
            entries[name] = desc.strip().replace("\n", " ")[:500]
        elif isinstance(skill, SkillDefinition):
            desc = skill.description or "(workflow)"
            entries[name] = f"[workflow] {desc.strip()[:500]}"

    return entries


def get_catalog_entries(skills_dir: str) -> Dict[str, str]:
    """Retorna el diccionario de entries (con cache).

    Args:
        skills_dir: Directorio de skills

    Returns:
        Dict {nombre: descripcion}
    """
    global _catalog_entries
    if _catalog_entries is None:
        _catalog_entries = _build_entries(skills_dir)
    return _catalog_entries


def generate_catalog_text(skills_dir: str) -> str:
    """Genera el catalogo compacto como texto para enviar a DeepSeek.

    Formato ultra-compacto para minimizar tokens:
        skill-name: descripcion breve

    Args:
        skills_dir: Directorio de skills

    Returns:
        Texto del catalogo (~2K tokens para ~49 skills)
    """
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    entries = get_catalog_entries(skills_dir)
    if not entries:
        return ""

    lines = [f"SKILLS DISPONIBLES ({len(entries)}):"]
    for name, desc in entries.items():
        lines.append(f"  {name}: {desc}")

    _catalog_cache = "\n".join(lines)
    return _catalog_cache


def load_requested_skills(
    skills_dir: str,
    requested_names: List[str],
    token_budget: int = 80000,
) -> Tuple[str, int, List[str]]:
    """Carga solo las skills que DeepSeek pidio.

    Respeta un presupuesto de tokens. Si una skill excede el
    presupuesto restante, se omite (sin truncar skills individuales).

    Args:
        skills_dir: Directorio de skills
        requested_names: Nombres de skills que DeepSeek pidio
        token_budget: Maximo de tokens para skills

    Returns:
        Tupla (contexto_formateado, tokens_usados, nombres_cargados)
    """
    if not requested_names:
        return "", 0, []

    loader = SkillLoader(skills_dir)
    parts = ["== SKILLS SOLICITADAS =="]
    total_tokens = 10  # overhead del header
    loaded_names = []

    for name in requested_names:
        skill = loader.load_one(name)
        if not skill or not isinstance(skill, KnowledgeSkill):
            continue

        skill_tokens = len(skill.content) // 4
        if total_tokens + skill_tokens > token_budget:
            # No truncar — simplemente omitir
            continue

        parts.append(f"\n--- {name} ---\n{skill.content}\n")
        total_tokens += skill_tokens
        loaded_names.append(name)

    if len(loaded_names) == 0:
        return "", 0, []

    parts.append("== FIN SKILLS ==")
    return "\n".join(parts), total_tokens, loaded_names


def invalidate_catalog_cache():
    """Invalida el cache del catalogo (si se agregan skills en runtime)."""
    global _catalog_cache, _catalog_entries
    _catalog_cache = None
    _catalog_entries = None
