"""
Semantic Engine — Motor semantico con TF-IDF, similitud coseno,
estimador Bayesiano, decaimiento temporal y test de tendencia Mann-Kendall.

Zero dependencias externas: solo stdlib de Python (math, re, collections).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# --- Mapa de acentos para normalizacion ---
_ACCENT_MAP = {
    "\u00e1": "a", "\u00e9": "e", "\u00ed": "i", "\u00f3": "o", "\u00fa": "u",
    "\u00c1": "A", "\u00c9": "E", "\u00cd": "I", "\u00d3": "O", "\u00da": "U",
    "\u00f1": "n", "\u00d1": "N", "\u00fc": "u", "\u00dc": "U",
}

_ACCENT_RE = re.compile("|".join(re.escape(k) for k in _ACCENT_MAP))


def _strip_accents(text: str) -> str:
    """Reemplaza caracteres acentuados por su equivalente ASCII."""
    return _ACCENT_RE.sub(lambda m: _ACCENT_MAP[m.group()], text)


# =========================================================================
# TF-IDF Vectorizer
# =========================================================================

class TFIDFVectorizer:
    """Vectorizador TF-IDF puro Python con soporte de bigramas."""

    def __init__(self) -> None:
        self.idf: Dict[str, float] = {}
        self._doc_count = 0

    # --- Tokenizacion ---

    def tokenize(self, text: str) -> List[str]:
        """Tokeniza texto: strip acentos, lowercase, unigramas + bigramas."""
        cleaned = _strip_accents(text).lower()
        words = re.findall(r"[a-z0-9]+", cleaned)
        # Unigramas
        tokens = list(words)
        # Bigramas: pares adyacentes unidos con _
        for i in range(len(words) - 1):
            tokens.append(f"{words[i]}_{words[i + 1]}")
        return tokens

    # --- Fit (calcular IDF) ---

    def fit(self, corpus: List[str]) -> "TFIDFVectorizer":
        """Calcula IDF a partir de un corpus de documentos."""
        n = len(corpus)
        self._doc_count = n
        df: Counter = Counter()
        for doc in corpus:
            # Contar cada termino una sola vez por documento
            unique_terms = set(self.tokenize(doc))
            for term in unique_terms:
                df[term] += 1
        # IDF(t) = log(N / (1 + df(t)))
        self.idf = {term: math.log(n / (1 + freq)) for term, freq in df.items()}
        return self

    # --- Transform (texto -> vector TF-IDF) ---

    def transform(self, text: str) -> Dict[str, float]:
        """Convierte un texto en un vector TF-IDF disperso (dict)."""
        tokens = self.tokenize(text)
        if not tokens:
            return {}
        total = len(tokens)
        tf = Counter(tokens)
        vector: Dict[str, float] = {}
        for term, count in tf.items():
            if term in self.idf:
                vector[term] = (count / total) * self.idf[term]
        return vector

    # --- Fit + Transform combinado ---

    def fit_transform(self, corpus: List[str]) -> List[Dict[str, float]]:
        """Fit en el corpus y transforma cada documento."""
        self.fit(corpus)
        return [self.transform(doc) for doc in corpus]


# =========================================================================
# Similitud Coseno
# =========================================================================

def cosine_similarity(
    vec_a: Dict[str, float],
    vec_b: Dict[str, float],
) -> float:
    """Calcula similitud coseno entre dos vectores dispersos (dicts)."""
    if not vec_a or not vec_b:
        return 0.0
    # Producto punto: solo en claves compartidas
    shared_keys = vec_a.keys() & vec_b.keys()
    dot = sum(vec_a[k] * vec_b[k] for k in shared_keys)
    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# =========================================================================
# Estimador Bayesiano (distribucion Beta)
# =========================================================================

def _normal_cdf(x: float) -> float:
    """Aproximacion de la CDF normal estandar usando erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class BayesianEstimator:
    """Estimador Bayesiano basado en distribucion Beta(alpha, beta)."""

    def __init__(self, alpha: float = 1.0, beta: float = 1.0) -> None:
        self.alpha = alpha
        self.beta = beta

    def update(self, successes: int, failures: int) -> None:
        """Actualiza con observaciones: alpha += exitos, beta += fallos."""
        self.alpha += successes
        self.beta += failures

    def mean(self) -> float:
        """Media de la distribucion Beta: alpha / (alpha + beta)."""
        return self.alpha / (self.alpha + self.beta)

    def variance(self) -> float:
        """Varianza de la distribucion Beta."""
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    def confidence_interval(self, level: float = 0.95) -> Tuple[float, float]:
        """Intervalo de confianza usando aproximacion normal, clamped a [0,1]."""
        # z-score para el nivel de confianza
        # Para 0.95 -> z ~ 1.96; usamos ppf via inversion
        z = _z_score_for_level(level)
        mu = self.mean()
        std = math.sqrt(self.variance())
        lower = max(0.0, mu - z * std)
        upper = min(1.0, mu + z * std)
        return (lower, upper)

    def risk_score(self, threshold: float = 0.5) -> float:
        """Probabilidad aproximada de que X < threshold (riesgo)."""
        mu = self.mean()
        std = math.sqrt(self.variance())
        if std == 0.0:
            return 0.0 if mu >= threshold else 1.0
        z = (threshold - mu) / std
        return _normal_cdf(z)

    @classmethod
    def from_stats(
        cls, successes: int, total: int
    ) -> "BayesianEstimator":
        """Crea estimador desde estadisticas: prior + observaciones."""
        return cls(alpha=successes + 1, beta=total - successes + 1)


def _z_score_for_level(level: float) -> float:
    """Retorna z-score aproximado para un nivel de confianza dado."""
    # Tabla comun de z-scores
    table = {
        0.90: 1.645,
        0.95: 1.960,
        0.99: 2.576,
    }
    if level in table:
        return table[level]
    # Aproximacion generica usando biseccion en normal CDF
    # Para niveles no tabulados, usamos busqueda simple
    alpha = (1.0 - level) / 2.0
    target = 1.0 - alpha
    # Biseccion entre 0 y 4
    lo, hi = 0.0, 4.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _normal_cdf(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# =========================================================================
# Decaimiento Temporal
# =========================================================================

def temporal_decay(age_days: float, half_life: float = 30.0) -> float:
    """Decaimiento exponencial: 1.0 a edad 0, 0.5 a edad = half_life."""
    clamped_age = max(0.0, age_days)
    return math.exp(-math.log(2) * clamped_age / half_life)


def weighted_score(
    base_score: float, age_days: float, half_life: float = 30.0
) -> float:
    """Score ponderado por decaimiento temporal."""
    return base_score * temporal_decay(age_days, half_life)


# =========================================================================
# Test de Tendencia Mann-Kendall
# =========================================================================

def mann_kendall_trend(
    values: List[float],
) -> Tuple[float, str]:
    """
    Test de tendencia Mann-Kendall simplificado.

    Retorna (tau, tendencia) donde tendencia es:
    - "increasing" si tau > 0.3
    - "decreasing" si tau < -0.3
    - "stable" en otro caso
    """
    n = len(values)
    if n < 3:
        return (0.0, "stable")

    # Contar pares concordantes y discordantes
    concordant = 0
    discordant = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            if values[j] > values[i]:
                concordant += 1
            elif values[j] < values[i]:
                discordant += 1
            # Empates no cuentan

    s = concordant - discordant
    # Numero total de pares
    total_pairs = n * (n - 1) / 2
    tau = s / total_pairs if total_pairs > 0 else 0.0

    if tau > 0.3:
        trend = "increasing"
    elif tau < -0.3:
        trend = "decreasing"
    else:
        trend = "stable"

    return (tau, trend)
