"""Herramienta MCP para deteccion y resolucion de conflictos de merge.

Expone la funcionalidad de git_intel como tool MCP para que Claude Code
pueda invocarla directamente via tool_use.

Acciones:
- detect: Lista archivos con conflictos
- resolve: Resuelve conflictos (heuristica o AI)
- preview: Muestra conflictos sin resolver
"""

import os
from pathlib import Path
from typing import List, Optional
from ..server.tool import BaseTool


class ResolveConflictsTool(BaseTool):
    """Detecta y resuelve conflictos de merge en un proyecto git."""

    def __init__(self, allowed_paths: List[str], client=None):
        super().__init__(
            name="resolve_conflicts",
            description=(
                "Detecta y resuelve conflictos de merge en un proyecto git. "
                "Acciones: 'detect' lista archivos con conflictos, "
                "'resolve' resuelve conflictos con heuristica o AI, "
                "'preview' muestra los conflictos sin modificar archivos."
            )
        )
        self.allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]
        self.client = client  # DeepSeekCodeClient para AI resolution

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["detect", "resolve", "preview"],
                    "description": (
                        "'detect': lista archivos con conflictos. "
                        "'resolve': resuelve conflictos automaticamente. "
                        "'preview': muestra conflictos sin modificar."
                    )
                },
                "project_path": {
                    "type": "string",
                    "description": "Ruta al proyecto con conflictos de merge."
                },
                "auto_apply": {
                    "type": "boolean",
                    "description": (
                        "Si True, escribe las resoluciones directamente en los archivos. "
                        "Si False (default), solo reporta las resoluciones propuestas."
                    ),
                    "default": False,
                },
            },
            "required": ["action", "project_path"],
        }

    async def execute(self, **kwargs) -> dict:
        """Ejecuta la accion solicitada sobre conflictos de merge."""
        action = kwargs.get("action", "detect")
        project_path = kwargs.get("project_path", "")
        auto_apply = kwargs.get("auto_apply", False)

        # Validar ruta
        try:
            resolved = Path(project_path).expanduser().resolve()
            if self.allowed_paths and not any(
                str(resolved).startswith(str(ap)) for ap in self.allowed_paths
            ):
                return {"error": f"Ruta no permitida: {project_path}"}
        except Exception as e:
            return {"error": f"Ruta invalida: {e}"}

        project_root = str(resolved)

        if action == "detect":
            return await self._detect(project_root)
        elif action == "preview":
            return await self._preview(project_root)
        elif action == "resolve":
            return await self._resolve(project_root, auto_apply)
        else:
            return {"error": f"Accion desconocida: {action}"}

    async def _detect(self, project_root: str) -> dict:
        """Detecta archivos con conflictos."""
        from deepseek_code.intelligence.git_intel import detect_conflicts
        files = detect_conflicts(project_root)
        return {
            "conflict_files": files,
            "count": len(files),
            "project": project_root,
        }

    async def _preview(self, project_root: str) -> dict:
        """Muestra conflictos sin resolver."""
        from deepseek_code.intelligence.git_intel import get_all_conflicts
        conflicts = get_all_conflicts(project_root)

        if not conflicts:
            return {"message": "No se encontraron conflictos de merge.", "count": 0}

        previews = []
        for c in conflicts[:20]:
            previews.append({
                "file": c.file_path,
                "index": c.conflict_index,
                "ours_preview": c.ours[:3000],
                "theirs_preview": c.theirs[:3000],
                "context_before": c.context_before[:2000],
            })

        return {
            "conflicts": previews,
            "count": len(conflicts),
            "files_affected": len(set(c.file_path for c in conflicts)),
        }

    async def _resolve(self, project_root: str, auto_apply: bool) -> dict:
        """Resuelve conflictos (heuristica simple sin AI por defecto)."""
        from deepseek_code.intelligence.git_intel import (
            get_all_conflicts,
            resolve_conflict_simple,
            apply_resolution,
        )

        conflicts = get_all_conflicts(project_root)
        if not conflicts:
            return {"message": "No se encontraron conflictos de merge.", "resolved": 0}

        # Agrupar conflictos por archivo
        files_conflicts: dict = {}
        for c in conflicts:
            files_conflicts.setdefault(c.file_path, []).append(c)

        resolutions_report = []
        total_resolved = 0

        for rel_path, file_conflicts in files_conflicts.items():
            full_path = os.path.join(project_root, rel_path)

            # Resolver cada conflicto del archivo
            resolution_codes = []
            for conflict in file_conflicts:
                resolution = resolve_conflict_simple(conflict)
                resolution_codes.append(resolution.resolved_content)
                resolutions_report.append(resolution.to_dict())

            # Aplicar resoluciones si se pidio
            if auto_apply:
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        original = f.read()
                    resolved = apply_resolution(rel_path, original, resolution_codes)
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(resolved)
                    total_resolved += len(file_conflicts)
                except (IOError, OSError) as e:
                    resolutions_report.append({
                        "file_path": rel_path,
                        "error": f"No se pudo escribir: {e}",
                    })
            else:
                total_resolved += len(file_conflicts)

        return {
            "resolved": total_resolved,
            "auto_applied": auto_apply,
            "resolutions": resolutions_report,
            "files_affected": len(files_conflicts),
        }
