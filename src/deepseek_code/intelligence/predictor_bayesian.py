"""Funciones Bayesianas para el predictor de salud del proyecto.

Separado de predictor.py para respetar el limite de 400 LOC.
Provee: probabilidad de fallo Bayesiana, slopes de tendencia,
score de riesgo compuesto, y construccion de intervalos de confianza.
"""

from typing import Dict, List, Tuple

from .semantic_engine import BayesianEstimator, mann_kendall_trend


def compute_bayesian_failure_rate(delegation_history: list) -> dict:
    """Calcula la probabilidad Bayesiana de fallo con CI.

    Returns:
        {"mean": float, "ci_lower": float, "ci_upper": float}
        or empty dict if no data
    """
    if not delegation_history:
        return {}

    successes = sum(1 for d in delegation_history if d.get("success", False))
    total = len(delegation_history)
    failures = total - successes

    bayes = BayesianEstimator.from_stats(failures, total)
    ci = bayes.confidence_interval(0.95)

    return {
        "mean": round(bayes.mean(), 4),
        "ci_lower": round(ci[0], 4),
        "ci_upper": round(ci[1], 4),
    }


def compute_trend_slopes(
    delegation_history: list,
    error_log: list,
) -> Dict[str, float]:
    """Calcula slopes de tendencia para indicadores clave.

    Usa Mann-Kendall trend test en ventanas deslizantes.
    Returns dict de {indicator: tau} donde tau es Kendall's tau.
    """
    slopes: Dict[str, float] = {}

    # Failure rate trend (ventanas deslizantes de 5)
    if len(delegation_history) >= 5:
        window = 5
        rates: List[float] = []
        for i in range(0, len(delegation_history) - window + 1):
            chunk = delegation_history[i : i + window]
            fails = sum(1 for d in chunk if not d.get("success", True))
            rates.append(fails / window)
        if len(rates) >= 3:
            tau, _trend = mann_kendall_trend(rates)
            slopes["failure_rate"] = round(tau, 4)

    # Error diversity trend (ventanas deslizantes de 5)
    if len(error_log) >= 5:
        window = 5
        counts: List[float] = []
        for i in range(0, len(error_log) - window + 1):
            chunk = error_log[i : i + window]
            unique_types = len(set(e.get("type", "unknown") for e in chunk))
            counts.append(float(unique_types))
        if len(counts) >= 3:
            tau, _trend = mann_kendall_trend(counts)
            slopes["error_diversity"] = round(tau, 4)

    return slopes


def compute_composite_risk(
    delegation_history: list,
    error_log: list,
    file_risks: list,
    tech_debt_trends: list,
) -> float:
    """Calcula score de riesgo compuesto 0-100.

    Pesos: 50% failure rate + 20% trends + 30% file/debt risks
    """
    # Componente 1: Probabilidad Bayesiana de fallo (0-1)
    failure_component = 0.0
    if delegation_history:
        successes = sum(1 for d in delegation_history if d.get("success", False))
        total = len(delegation_history)
        if total > 0:
            failures = total - successes
            bayes = BayesianEstimator.from_stats(failures, total)
            failure_component = bayes.mean()

    # Componente 2: Severidad de tendencia (0-1)
    trend_component = 0.0
    slopes = compute_trend_slopes(delegation_history, error_log)
    if slopes:
        trend_vals: List[float] = []
        for key, tau in slopes.items():
            # tau positivo en failure_rate = malo
            if "failure" in key:
                trend_vals.append(max(0.0, tau))
            else:
                trend_vals.append(abs(tau))
        if trend_vals:
            trend_component = min(1.0, sum(trend_vals) / len(trend_vals))

    # Componente 3: Riesgos de archivos y deuda tecnica (0-1)
    risk_component = 0.0
    if file_risks:
        critical = sum(
            1 for f in file_risks if getattr(f, "risk_level", "") == "critical"
        )
        warning = sum(
            1 for f in file_risks if getattr(f, "risk_level", "") == "warning"
        )
        risk_component = min(1.0, critical * 0.3 + warning * 0.1)

    high_debt = sum(
        1 for t in tech_debt_trends if getattr(t, "severity", "") == "high"
    )
    if high_debt:
        risk_component = min(1.0, risk_component + high_debt * 0.2)

    # Compuesto: promedio ponderado escalado a 0-100
    composite = (
        0.5 * failure_component + 0.2 * trend_component + 0.3 * risk_component
    )

    return round(composite * 100, 1)


def build_confidence_intervals(
    delegation_history: list,
) -> Dict[str, Tuple[float, float]]:
    """Construye intervalos de confianza para indicadores clave."""
    intervals: Dict[str, Tuple[float, float]] = {}

    if delegation_history:
        fr = compute_bayesian_failure_rate(delegation_history)
        if fr:
            intervals["failure_rate"] = (fr["ci_lower"], fr["ci_upper"])

    return intervals
