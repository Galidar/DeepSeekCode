"""Integracion de SurgicalMemory con los flujos de delegacion.

Funciones de alto nivel que encapsulan el flujo completo:
pre_delegation() -> inyecta contexto del proyecto
post_delegation() -> aprende de resultados de la delegacion
"""

import os
import sys
from typing import Optional, Tuple

from .store import SurgicalStore
from .collector import detect_project_root, extract_claude_md
from .injector import build_briefing
from .learner import learn_from_delegation


def pre_delegation(
    appdata_dir: str,
    task: str,
    template_path: Optional[str] = None,
    context_path: Optional[str] = None,
    project_context_path: Optional[str] = None,
    token_budget: int = 3000,
) -> Tuple[str, Optional[SurgicalStore]]:
    """Prepara el briefing de SurgicalMemory para inyectar antes de delegar.

    Detecta el proyecto, carga la memoria, y construye el briefing.
    Retorna el briefing como string y el store cargado (para post_delegation).

    Args:
        appdata_dir: Directorio APPDATA para almacenar stores
        task: Descripcion de la tarea
        template_path: Ruta al template (para detectar proyecto)
        context_path: Ruta al contexto (para detectar proyecto)
        project_context_path: Ruta explicita a CLAUDE.md o similar
        token_budget: Tokens maximos para el briefing

    Returns:
        Tupla (briefing_string, store_instance)
        Si no se detecta proyecto, retorna ("", None)
    """
    try:
        return _pre_delegation_inner(
            appdata_dir, task, template_path,
            context_path, project_context_path, token_budget,
        )
    except Exception as e:
        print(f"[surgical] Error en pre_delegation: {e}", file=sys.stderr)
        return "", None


def _pre_delegation_inner(
    appdata_dir, task, template_path,
    context_path, project_context_path, token_budget,
):
    """Logica interna de pre_delegation (separada para manejo de errores)."""
    # Detectar proyecto
    project_root = None
    for path in [template_path, context_path, project_context_path]:
        if path:
            project_root = detect_project_root(path)
            if project_root:
                break

    if not project_root:
        return "", None

    # Cargar store
    store = SurgicalStore(appdata_dir)
    store.load(project_root)

    # Extraer CLAUDE.md
    claude_md = None
    if project_context_path and os.path.exists(project_context_path):
        try:
            with open(project_context_path, 'r', encoding='utf-8') as f:
                claude_md = f.read()
        except IOError:
            pass

    if not claude_md:
        claude_md = extract_claude_md(project_root)

    # Si es primera vez, inicializar arquitectura desde CLAUDE.md
    arch = store.data.get("architecture", {})
    if claude_md and not arch.get("description"):
        _initialize_from_claude_md(store, claude_md, project_root)

    # Construir briefing
    briefing = build_briefing(
        store.data, task,
        claude_md_content=claude_md,
        token_budget=token_budget,
    )

    if briefing:
        print(
            f"[surgical] Briefing: {len(briefing)} chars "
            f"({project_root})",
            file=sys.stderr,
        )

    return briefing, store


def post_delegation(
    store: Optional[SurgicalStore],
    task: str,
    mode: str,
    success: bool,
    response: str,
    validation: Optional[dict] = None,
    duration_s: float = 0.0,
):
    """Registra los resultados de una delegacion para aprendizaje.

    Args:
        store: SurgicalStore del proyecto (de pre_delegation)
        task: Tarea ejecutada
        mode: Modo de delegacion ("delegate", "quantum", "multi_step")
        success: Si fue exitosa
        response: Respuesta de DeepSeek
        validation: Resultado de validacion
        duration_s: Duracion
    """
    if not store:
        return

    try:
        learn_from_delegation(
            store, task, mode, success,
            response, validation, duration_s,
        )
    except Exception as e:
        print(f"[surgical] Error en post_delegation: {e}", file=sys.stderr)


def _initialize_from_claude_md(
    store: SurgicalStore,
    claude_md: str,
    project_root: str,
):
    """Inicializa el store con informacion extraida de CLAUDE.md."""
    project_name = os.path.basename(project_root)

    # Extraer descripcion de primeras lineas no vacias
    lines = claude_md.splitlines()
    description_lines = []
    for line in lines[:20]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            description_lines.append(stripped)
    description = " ".join(description_lines[:5])

    # Extraer estructura de bloques de codigo
    structure = ""
    in_code_block = False
    structure_lines = []
    found_structure_header = False

    for line in lines:
        lower = line.lower().strip()

        # Detectar encabezado de estructura
        if not found_structure_header and (
            "estructura" in lower or "structure" in lower
        ) and lower.startswith("#"):
            found_structure_header = True
            continue

        if found_structure_header:
            if line.strip().startswith("```") and not in_code_block:
                in_code_block = True
                continue
            if line.strip().startswith("```") and in_code_block:
                in_code_block = False
                break
            if in_code_block:
                structure_lines.append(line)

    if structure_lines:
        structure = "\n".join(structure_lines[:30])

    store.set_architecture(
        description=f"Proyecto: {project_name}. {description[:200]}",
        structure=structure[:500],
    )
