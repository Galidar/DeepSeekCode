"""Integracion de GlobalMemory con los flujos de delegacion.

Funciones de alto nivel fail-safe que encapsulan el flujo completo:
global_pre_delegation() -> inyecta perfil personal del desarrollador
global_post_delegation() -> aprende de resultados de la delegacion

Si algo falla, retorna valores neutros y todo funciona como antes.
"""

import sys
from typing import List, Optional, Tuple

from .global_store import GlobalStore
from .global_learner import learn_global
from .global_injector import build_global_briefing


def global_pre_delegation(
    appdata_dir: str,
    task: str,
    token_budget: int = 2000,
) -> Tuple[str, Optional[GlobalStore]]:
    """Prepara el briefing de GlobalMemory para inyectar antes de delegar.

    Carga la memoria global cross-proyecto y construye un briefing
    compacto con el perfil personal del desarrollador.

    Args:
        appdata_dir: Directorio APPDATA para almacenar datos
        task: Descripcion de la tarea (para futuro contexto)
        token_budget: Tokens maximos para el briefing

    Returns:
        Tupla (briefing_string, store_instance)
        Si falla, retorna ("", None) y todo funciona normal
    """
    try:
        return _pre_delegation_inner(appdata_dir, task, token_budget)
    except Exception as e:
        print(f"[global_memory] Error en pre_delegation: {e}", file=sys.stderr)
        return "", None


def _pre_delegation_inner(
    appdata_dir: str,
    task: str,
    token_budget: int,
) -> Tuple[str, Optional[GlobalStore]]:
    """Logica interna de pre_delegation (separada para manejo de errores)."""
    if not appdata_dir:
        return "", None

    store = GlobalStore(appdata_dir)
    store.load()

    briefing = build_global_briefing(store.data, token_budget=token_budget)

    if briefing:
        total = store.data.get("total_delegations", 0)
        print(
            f"[global_memory] Briefing: {len(briefing)} chars "
            f"({total} delegaciones acumuladas)",
            file=sys.stderr,
        )

    return briefing, store


def global_post_delegation(
    store: Optional[GlobalStore],
    task: str,
    mode: str,
    success: bool,
    response: str,
    validation: Optional[dict] = None,
    duration_s: float = 0.0,
    skills_injected: Optional[List[str]] = None,
    token_usage: Optional[dict] = None,
    project_name: str = "",
):
    """Registra los resultados de una delegacion para aprendizaje global.

    Args:
        store: GlobalStore cargado (de global_pre_delegation)
        task: Tarea ejecutada
        mode: Modo de delegacion ("delegate", "quantum", "multi_step")
        success: Si la respuesta fue valida
        response: Respuesta de DeepSeek
        validation: Resultado de validate_delegate_response
        duration_s: Duracion en segundos
        skills_injected: Lista de nombres de skills inyectadas
        token_usage: Desglose de tokens consumidos
        project_name: Nombre del proyecto actual
    """
    if not store:
        return

    try:
        learn_global(
            store, task, mode, success, response,
            validation=validation,
            duration_s=duration_s,
            skills_injected=skills_injected,
            token_usage=token_usage,
            project_name=project_name,
        )
    except Exception as e:
        print(f"[global_memory] Error en post_delegation: {e}", file=sys.stderr)


def get_injected_skill_names(task_text: str) -> List[str]:
    """Obtiene la lista de nombres de skills que se inyectarian para una tarea.

    Combina CORE_SKILLS (siempre inyectadas) con domain skills detectadas
    por keywords. No carga contenido, solo nombres.

    Args:
        task_text: Texto de la tarea para detectar skills relevantes

    Returns:
        Lista de nombres de skills (core + domain)
    """
    try:
        from deepseek_code.skills.skill_constants import CORE_SKILLS
        from deepseek_code.skills.skill_injector import detect_relevant_skills

        domain_skills = detect_relevant_skills(task_text, exclude=CORE_SKILLS)
        return list(CORE_SKILLS) + domain_skills
    except Exception:
        return []


def detect_project_name(
    template_path: Optional[str] = None,
    context_path: Optional[str] = None,
) -> str:
    """Intenta detectar el nombre del proyecto desde las rutas de archivos.

    Busca el directorio raiz del proyecto subiendo por el arbol.

    Args:
        template_path: Ruta al template (para detectar proyecto)
        context_path: Ruta al contexto (para detectar proyecto)

    Returns:
        Nombre del proyecto o "" si no se detecta
    """
    try:
        from deepseek_code.surgical.collector import detect_project_root
        import os

        for path in [template_path, context_path]:
            if path:
                root = detect_project_root(path)
                if root:
                    return os.path.basename(root)
        return ""
    except Exception:
        return ""
