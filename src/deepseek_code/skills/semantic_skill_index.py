"""Indice semantico de skills usando TF-IDF para matching por similitud.

Reemplaza el keyword matching basico con busqueda semantica.
El keyword map se preserva como fallback — no se elimina.

Uso:
    idx = SemanticSkillIndex()
    idx.build_from_keywords(SKILL_KEYWORD_MAP)
    results = idx.search("crear un juego 2d con fisicas", top_k=5)
    # -> [("canvas-2d-reference", 0.82), ("physics-simulation", 0.71), ...]
"""

from typing import List, Tuple, Dict, Optional
from deepseek_code.intelligence.semantic_engine import (
    TFIDFVectorizer,
    cosine_similarity,
    BayesianEstimator,
)


class SemanticSkillIndex:
    """Indice pre-computado de skills para busqueda semantica via TF-IDF."""

    def __init__(self):
        self._vectorizer = TFIDFVectorizer()
        self._corpus_vectors: Dict[str, Dict[str, float]] = {}
        self._skill_names: List[str] = []
        self._built = False

    def build_from_keywords(self, keyword_map: dict):
        """Construye el indice TF-IDF desde SKILL_KEYWORD_MAP.

        Cada skill se representa como: "nombre_sin_guiones keyword1 keyword2 ..."
        Esto permite que el vectorizer capture tanto el nombre como los keywords.
        """
        corpus_texts = []
        self._skill_names = []

        for name, keywords in keyword_map.items():
            # Expand skill name: "canvas-2d-reference" -> "canvas 2d reference"
            name_expanded = name.replace("-", " ").replace("_", " ")
            text = f"{name_expanded} {' '.join(keywords)}"
            corpus_texts.append(text)
            self._skill_names.append(name)

        vectors = self._vectorizer.fit_transform(corpus_texts)
        self._corpus_vectors = dict(zip(self._skill_names, vectors))
        self._built = True

    def search(self, task: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Busca las top-k skills mas relevantes para la tarea dada.

        Returns:
            Lista de (skill_name, similarity_score) ordenada descendente.
        """
        if not task or not task.strip() or not self._built:
            return []

        query_vec = self._vectorizer.transform(task)
        if not query_vec:
            return []

        scores = []
        for name, vec in self._corpus_vectors.items():
            sim = cosine_similarity(query_vec, vec)
            if sim > 0.0:
                scores.append((name, sim))

        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    def search_with_boost(
        self,
        task: str,
        top_k: int = 5,
        skill_stats: Optional[Dict] = None,
    ) -> List[Tuple[str, float]]:
        """Busca skills con boost Bayesiano basado en success rate historico.

        El score final = similarity * bayesian_mean
        donde bayesian_mean = Beta(successes+1, failures+1).mean()
        """
        # Get more candidates than needed, then boost and re-rank
        candidates = self.search(task, top_k=top_k * 3)

        if not skill_stats or not candidates:
            return candidates[:top_k]

        boosted = []
        for name, sim in candidates:
            stat = skill_stats.get(name, {})
            successes = stat.get("with_success", 0)
            total = stat.get("injected", 0)

            if total > 0:
                bayes = BayesianEstimator.from_stats(successes, total)
                boost = bayes.mean()
            else:
                boost = 0.5  # Prior neutral — sin datos

            boosted.append((name, sim * boost))

        boosted.sort(key=lambda x: -x[1])
        return boosted[:top_k]
