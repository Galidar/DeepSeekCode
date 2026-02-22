"""Almacenamiento persistente por proyecto para SurgicalMemory.

Cada proyecto tiene un archivo JSON en APPDATA_DIR/surgical_memory/
con secciones estructuradas: architecture, conventions, error_log,
delegation_history, patterns, feedback_rules.
"""

import json
import os
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from deepseek_code.intelligence.semantic_engine import (
    TFIDFVectorizer, cosine_similarity, temporal_decay,
)


# Limites de seccion para compactacion
MAX_ERROR_LOG_ENTRIES = 30
MAX_DELEGATION_HISTORY = 20
MAX_PATTERNS = 15
MAX_FEEDBACK_RULES = 20
MAX_SHADOW_CORRECTIONS = 20
MAX_FAILURE_ANALYSES = 15
MAX_STORE_BYTES = 512 * 1024  # 512 KB por proyecto


def _make_project_id(path: str) -> str:
    """Genera un ID unico para el proyecto basado en su ruta."""
    normalized = os.path.normpath(os.path.abspath(path)).lower()
    short_hash = hashlib.md5(normalized.encode()).hexdigest()[:8]
    name = os.path.basename(normalized)
    return f"{name}_{short_hash}"


def _default_store() -> dict:
    """Retorna un store vacio con estructura valida."""
    return {
        "version": 1,
        "project_id": "",
        "project_path": "",
        "project_name": "",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "architecture": {
            "description": "",
            "structure": "",
            "key_decisions": [],
        },
        "conventions": {
            "naming": "",
            "imports": "",
            "patterns": "",
            "custom_rules": [],
        },
        "error_log": [],
        "delegation_history": [],
        "patterns": [],
        "feedback_rules": [],
        "shadow_corrections": [],
        "failure_analyses": [],
    }


class SurgicalStore:
    """Gestiona la memoria persistente de un proyecto.

    Almacena JSON en APPDATA/surgical_memory/{project_name}_{hash}.json
    con compactacion automatica de secciones que exceden limites.
    """

    def __init__(self, base_dir: str):
        self.base_dir = os.path.join(base_dir, "surgical_memory")
        os.makedirs(self.base_dir, exist_ok=True)
        self.data = _default_store()
        self._loaded_path = None

    def load(self, project_path: str) -> dict:
        """Carga el store de un proyecto. Crea uno nuevo si no existe."""
        project_id = _make_project_id(project_path)
        file_path = os.path.join(self.base_dir, f"{project_id}.json")
        self._loaded_path = file_path

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                    return self.data
            except (json.JSONDecodeError, IOError):
                pass

        self.data = _default_store()
        self.data["project_id"] = project_id
        self.data["project_path"] = project_path
        self.data["project_name"] = os.path.basename(project_path)
        return self.data

    def save(self):
        """Guarda el store actual a disco con compactacion."""
        if not self._loaded_path:
            return
        self.data["updated_at"] = datetime.now().isoformat()
        self._compact()
        try:
            with open(self._loaded_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            import sys
            print(f"[surgical] Error guardando store: {e}", file=sys.stderr)

    def _entry_relevance(self, entry: dict, half_life: float = 30.0) -> float:
        """Calcula relevancia de una entrada: decay(age) * (1 + frequency_bonus)."""
        timestamp = entry.get("timestamp", "")
        age_days = 0.0
        if timestamp:
            try:
                entry_dt = datetime.fromisoformat(timestamp)
                age_days = max(0, (datetime.now() - entry_dt).total_seconds() / 86400)
            except (ValueError, TypeError):
                age_days = 0.0

        decay = temporal_decay(age_days, half_life)

        freq = max(
            entry.get("use_count", 0),
            entry.get("occurrences", 0),
            entry.get("frequency", 0),
            1,
        )
        return decay * (1.0 + 0.1 * (freq - 1))

    def _compact(self):
        """Compacta secciones con relevancia inteligente (decay + frecuencia)."""
        # error_log: keep top N by relevance instead of FIFO
        el = self.data.get("error_log", [])
        if len(el) > MAX_ERROR_LOG_ENTRIES:
            scored = [(e, self._entry_relevance(e)) for e in el]
            scored.sort(key=lambda x: -x[1])
            self.data["error_log"] = [e for e, _ in scored[:MAX_ERROR_LOG_ENTRIES]]

        # delegation_history: keep top N by relevance
        dh = self.data.get("delegation_history", [])
        if len(dh) > MAX_DELEGATION_HISTORY:
            scored = [(d, self._entry_relevance(d)) for d in dh]
            scored.sort(key=lambda x: -x[1])
            self.data["delegation_history"] = [d for d, _ in scored[:MAX_DELEGATION_HISTORY]]

        # patterns: keep by use_count (already smart)
        pa = self.data.get("patterns", [])
        if len(pa) > MAX_PATTERNS:
            sorted_p = sorted(pa, key=lambda x: x.get("use_count", 0), reverse=True)
            self.data["patterns"] = sorted_p[:MAX_PATTERNS]

        # feedback_rules: keep by occurrences (already smart)
        fr = self.data.get("feedback_rules", [])
        if len(fr) > MAX_FEEDBACK_RULES:
            sorted_r = sorted(fr, key=lambda x: x.get("occurrences", 0), reverse=True)
            self.data["feedback_rules"] = sorted_r[:MAX_FEEDBACK_RULES]

        # shadow_corrections: keep by frequency (already smart)
        sc = self.data.get("shadow_corrections", [])
        if len(sc) > MAX_SHADOW_CORRECTIONS:
            sorted_sc = sorted(sc, key=lambda x: x.get("frequency", 0), reverse=True)
            self.data["shadow_corrections"] = sorted_sc[:MAX_SHADOW_CORRECTIONS]

        # failure_analyses: keep top N by relevance
        fa = self.data.get("failure_analyses", [])
        if len(fa) > MAX_FAILURE_ANALYSES:
            scored = [(f, self._entry_relevance(f)) for f in fa]
            scored.sort(key=lambda x: -x[1])
            self.data["failure_analyses"] = [f for f, _ in scored[:MAX_FAILURE_ANALYSES]]

    def add_error(self, error_entry: dict):
        """Agrega una entrada al error_log."""
        error_entry["timestamp"] = datetime.now().isoformat()
        self.data.setdefault("error_log", []).append(error_entry)

    def add_delegation(self, delegation_entry: dict):
        """Agrega una entrada al delegation_history."""
        delegation_entry["timestamp"] = datetime.now().isoformat()
        self.data.setdefault("delegation_history", []).append(delegation_entry)

    def add_pattern(self, pattern_entry: dict):
        """Agrega o actualiza un patron exitoso."""
        patterns = self.data.setdefault("patterns", [])
        for existing in patterns:
            if existing.get("name") == pattern_entry.get("name"):
                existing["use_count"] = existing.get("use_count", 0) + 1
                existing["last_used"] = datetime.now().isoformat()
                return
        pattern_entry["use_count"] = 1
        pattern_entry["created_at"] = datetime.now().isoformat()
        patterns.append(pattern_entry)

    def add_feedback_rule(self, rule: dict):
        """Agrega o refuerza una regla aprendida."""
        rules = self.data.setdefault("feedback_rules", [])
        for existing in rules:
            if existing.get("trigger") == rule.get("trigger"):
                existing["occurrences"] = existing.get("occurrences", 0) + 1
                existing["last_seen"] = datetime.now().isoformat()
                return
        rule["occurrences"] = 1
        rule["created_at"] = datetime.now().isoformat()
        rules.append(rule)

    def set_architecture(self, description: str = "", structure: str = "",
                         key_decisions: list = None):
        """Establece o actualiza la informacion de arquitectura."""
        arch = self.data.setdefault("architecture", {})
        if description:
            arch["description"] = description
        if structure:
            arch["structure"] = structure
        if key_decisions:
            arch["key_decisions"] = key_decisions

    def add_shadow_correction(self, correction: dict):
        """Agrega una correccion aprendida del usuario (shadow learning)."""
        corrections = self.data.setdefault("shadow_corrections", [])
        for existing in corrections:
            if existing.get("pattern_type") == correction.get("pattern_type"):
                existing["frequency"] = existing.get("frequency", 0) + 1
                existing["last_seen"] = datetime.now().isoformat()
                if correction.get("description"):
                    existing["description"] = correction["description"]
                return
        correction.setdefault("first_seen", datetime.now().isoformat())
        correction.setdefault("frequency", 1)
        corrections.append(correction)

    def add_failure_analysis(self, analysis: dict):
        """Agrega un analisis de falla del introspective debugger."""
        analyses = self.data.setdefault("failure_analyses", [])
        analysis["timestamp"] = datetime.now().isoformat()
        analyses.append(analysis)

    def set_conventions(self, **kwargs):
        """Establece o actualiza las convenciones."""
        conv = self.data.setdefault("conventions", {})
        for key, value in kwargs.items():
            if value:
                conv[key] = value

    def find_relevant(self, query: str, section: str, top_k: int = 5) -> list:
        """Busca entradas semanticamente relevantes en una seccion del store.

        Usa TF-IDF + cosine similarity para encontrar las entradas mas
        relevantes al query dado, ponderadas por decay temporal.
        """
        if not query or not query.strip():
            return []

        entries = self.data.get(section, [])
        if not entries:
            return []

        # Build text representation of each entry
        _text_keys = (
            "type", "message", "description", "task",
            "pattern_type", "name", "trigger", "root_cause",
        )
        texts = []
        for entry in entries:
            parts = []
            for key in _text_keys:
                val = entry.get(key, "")
                if val:
                    parts.append(str(val))
            texts.append(" ".join(parts) if parts else "")

        # TF-IDF vectorize
        vectorizer = TFIDFVectorizer()
        corpus = texts + [query]
        vectors = vectorizer.fit_transform(corpus)

        query_vec = vectors[-1]
        entry_vecs = vectors[:-1]

        if not query_vec:
            return []

        # Score = cosine_similarity * relevance_decay
        scored = []
        for i, (entry, vec) in enumerate(zip(entries, entry_vecs)):
            sim = cosine_similarity(query_vec, vec)
            if sim > 0.0:
                relevance = self._entry_relevance(entry)
                scored.append((entry, sim * relevance))

        # Fallback: token overlap for small corpora where IDF zeroes out
        if not scored:
            query_tokens = set(vectorizer.tokenize(query))
            for i, (entry, text) in enumerate(zip(entries, texts)):
                doc_tokens = set(vectorizer.tokenize(text))
                overlap = len(query_tokens & doc_tokens)
                if overlap > 0:
                    total = len(query_tokens | doc_tokens) or 1
                    jaccard = overlap / total
                    relevance = self._entry_relevance(entry)
                    scored.append((entry, jaccard * relevance))

        scored.sort(key=lambda x: -x[1])
        return [entry for entry, score in scored[:top_k]]
