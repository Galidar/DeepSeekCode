"""Almacenamiento persistente global para GlobalMemory.

Un solo archivo JSON en APPDATA/DeepSeek-Code/global_memory.json
que acumula aprendizaje cross-proyecto del usuario.
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# Limites de compactacion
MAX_SKILL_COMBOS = 30
MAX_CROSS_ERRORS = 20
MAX_TASK_KEYWORDS = 50
MAX_STORE_BYTES = 256 * 1024  # 256 KB


def _default_global_data() -> dict:
    """Retorna datos globales vacios con estructura valida."""
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "total_delegations": 0,
        "code_style": {
            "let_count": 0, "const_count": 0, "let_preference": True,
            "camel_count": 0, "snake_count": 0, "naming_preference": "camelCase",
            "comment_es": 0, "comment_en": 0, "comment_lang": "es",
        },
        "skill_stats": {},
        "skill_combos": [],
        "complexity_stats": {
            "avg_input_tokens": 0, "avg_todos": 0,
            "sweet_spot_todos": 5, "sweet_spot_input_tokens": 40000,
            "successful_samples": 0,
        },
        "mode_stats": {
            "delegate": {"total": 0, "successes": 0, "avg_duration": 0.0},
            "quantum": {"total": 0, "successes": 0, "avg_duration": 0.0},
            "multi_step": {"total": 0, "successes": 0, "avg_duration": 0.0},
        },
        "cross_project_errors": [],
        "task_keyword_success": {},
    }


class GlobalStore:
    """Gestiona la memoria global cross-proyecto.

    Almacena JSON en APPDATA/DeepSeek-Code/global_memory.json
    con compactacion automatica.
    """

    def __init__(self, appdata_dir: str):
        self.file_path = os.path.join(appdata_dir, "global_memory.json")
        self.data = _default_global_data()

    def load(self) -> dict:
        """Carga el archivo global. Crea uno nuevo si no existe."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                    return self.data
            except (json.JSONDecodeError, IOError):
                pass
        self.data = _default_global_data()
        return self.data

    def save(self):
        """Guarda los datos con compactacion automatica."""
        self.data["updated_at"] = datetime.now().isoformat()
        self._compact()
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"[global_memory] Error guardando: {e}", file=sys.stderr)

    def _compact(self):
        """Compacta secciones que exceden limites."""
        # skill_combos: max 30, por count descendente
        combos = self.data.get("skill_combos", [])
        if len(combos) > MAX_SKILL_COMBOS:
            sorted_c = sorted(combos, key=lambda x: x.get("count", 0), reverse=True)
            self.data["skill_combos"] = sorted_c[:MAX_SKILL_COMBOS]

        # cross_project_errors: max 20, por count descendente
        errors = self.data.get("cross_project_errors", [])
        if len(errors) > MAX_CROSS_ERRORS:
            sorted_e = sorted(errors, key=lambda x: x.get("count", 0), reverse=True)
            self.data["cross_project_errors"] = sorted_e[:MAX_CROSS_ERRORS]

        # task_keyword_success: max 50, por total descendente
        keywords = self.data.get("task_keyword_success", {})
        if len(keywords) > MAX_TASK_KEYWORDS:
            sorted_kw = sorted(
                keywords.items(), key=lambda x: x[1].get("total", 0), reverse=True
            )
            self.data["task_keyword_success"] = dict(sorted_kw[:MAX_TASK_KEYWORDS])

        # skill_stats: purgar skills con <2 inyecciones y >90 dias sin uso
        self._purge_stale_skills()

    def _purge_stale_skills(self):
        """Elimina skill_stats con pocas inyecciones y sin uso reciente."""
        stats = self.data.get("skill_stats", {})
        if len(stats) <= 30:
            return
        now = datetime.now()
        to_remove = []
        for name, st in stats.items():
            if st.get("injected", 0) < 2:
                last = st.get("last_used", "")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if (now - last_dt).days > 90:
                            to_remove.append(name)
                    except ValueError:
                        to_remove.append(name)
        for name in to_remove:
            del stats[name]

    def update_skill_stat(self, skill_name: str, success: bool, truncated: bool):
        """Actualiza estadisticas de una skill inyectada."""
        stats = self.data.setdefault("skill_stats", {})
        if skill_name not in stats:
            stats[skill_name] = {
                "injected": 0, "with_success": 0, "with_truncation": 0,
                "success_rate": 1.0, "last_used": "",
            }
        st = stats[skill_name]
        st["injected"] += 1
        if success:
            st["with_success"] += 1
        if truncated:
            st["with_truncation"] += 1
        st["success_rate"] = round(st["with_success"] / st["injected"], 3)
        st["last_used"] = datetime.now().isoformat()

    def update_skill_combo(self, skill_names: List[str], success: bool):
        """Actualiza estadisticas de combinacion de skills."""
        if len(skill_names) < 2:
            return
        combo_key = sorted(skill_names[:4])
        combos = self.data.setdefault("skill_combos", [])
        for combo in combos:
            if sorted(combo.get("skills", [])) == combo_key:
                combo["count"] += 1
                if success:
                    combo["successes"] += 1
                combo["success_rate"] = round(
                    combo["successes"] / combo["count"], 3
                )
                return
        combos.append({
            "skills": combo_key, "count": 1,
            "successes": 1 if success else 0,
            "success_rate": 1.0 if success else 0.0,
        })

    def add_cross_error(self, error_type: str, project_name: str):
        """Registra un error cross-proyecto."""
        errors = self.data.setdefault("cross_project_errors", [])
        for err in errors:
            if err.get("type") == error_type:
                err["count"] += 1
                if project_name not in err.get("projects", []):
                    err["projects"].append(project_name)
                err["last_seen"] = datetime.now().isoformat()
                return
        errors.append({
            "type": error_type, "count": 1,
            "projects": [project_name],
            "last_seen": datetime.now().isoformat(),
        })

    def update_task_keyword(self, keyword: str, success: bool):
        """Actualiza estadisticas de keyword de tarea."""
        keywords = self.data.setdefault("task_keyword_success", {})
        if keyword not in keywords:
            keywords[keyword] = {"total": 0, "successes": 0}
        kw = keywords[keyword]
        kw["total"] += 1
        if success:
            kw["successes"] += 1
