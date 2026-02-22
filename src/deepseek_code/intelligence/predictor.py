"""Predictive Intelligence — Deteccion proactiva de tech debt y riesgos.

Analiza datos de SurgicalMemory y GlobalMemory para detectar tendencias,
predecir archivos problematicos y generar reportes de salud del proyecto.

No modifica ningun store — es puramente de lectura y analisis.
"""

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class FileRisk:
    """Archivo en riesgo de exceder el limite de lineas."""
    path: str
    current_lines: int
    limit: int
    percentage: float         # 0.0 - 1.0
    risk_level: str           # "safe", "warning", "critical"


@dataclass
class ErrorCluster:
    """Grupo de errores recurrentes del mismo tipo."""
    error_type: str
    count: int
    recent_count: int         # Cuantos en los ultimos 10 registros
    trend: str                # "increasing", "stable", "decreasing"
    examples: List[str]


@dataclass
class TechDebtTrend:
    """Tendencia de deuda tecnica detectada."""
    indicator: str            # "truncation_rate", "error_frequency", etc.
    description: str
    severity: str             # "low", "medium", "high"
    value: float
    threshold: float


@dataclass
class HealthReport:
    """Reporte completo de salud predictiva del proyecto."""
    generated_at: str
    project_name: str
    risk_level: str           # "healthy", "warning", "critical"
    file_risks: List[FileRisk]
    error_clusters: List[ErrorCluster]
    tech_debt_trends: List[TechDebtTrend]
    recommendations: List[str]
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serializa a diccionario para JSON output."""
        return {
            "generated_at": self.generated_at,
            "project_name": self.project_name,
            "risk_level": self.risk_level,
            "file_risks": [
                {"path": f.path, "lines": f.current_lines,
                 "limit": f.limit, "pct": round(f.percentage * 100, 1),
                 "risk": f.risk_level}
                for f in self.file_risks
            ],
            "error_clusters": [
                {"type": c.error_type, "count": c.count,
                 "recent": c.recent_count, "trend": c.trend,
                 "examples": c.examples[:3]}
                for c in self.error_clusters
            ],
            "tech_debt_trends": [
                {"indicator": t.indicator, "description": t.description,
                 "severity": t.severity, "value": round(t.value, 3),
                 "threshold": t.threshold}
                for t in self.tech_debt_trends
            ],
            "recommendations": self.recommendations,
            "stats": self.stats,
        }


def generate_health_report(
    store_data: Optional[dict] = None,
    global_data: Optional[dict] = None,
    project_root: Optional[str] = None,
    line_limit: int = 400,
) -> HealthReport:
    """Genera reporte predictivo de salud del proyecto.

    Args:
        store_data: Datos del SurgicalStore (dict crudo del JSON)
        global_data: Datos del GlobalStore (dict crudo del JSON)
        project_root: Ruta raiz del proyecto para escaneo de archivos
        line_limit: Limite de lineas por archivo (default 400)

    Returns:
        HealthReport con riesgos, tendencias y recomendaciones
    """
    store_data = store_data or {}
    global_data = global_data or {}

    # 1. Escanear archivos del proyecto
    file_risks = []
    if project_root and os.path.isdir(project_root):
        file_risks = _predict_file_risks(project_root, line_limit)

    # 2. Identificar clusters de errores
    error_log = store_data.get("error_log", [])
    error_clusters = _identify_error_clusters(error_log)

    # 3. Detectar tendencias de tech debt
    delegation_history = store_data.get("delegation_history", [])
    tech_debt_trends = _detect_tech_debt_trends(delegation_history, error_log)

    # 4. Agregar tendencias cross-proyecto desde GlobalMemory
    cross_errors = global_data.get("cross_project_errors", [])
    if cross_errors:
        tech_debt_trends.extend(_detect_cross_project_trends(cross_errors))

    # 5. Generar recomendaciones priorizadas
    recommendations = _generate_recommendations(
        file_risks, error_clusters, tech_debt_trends,
    )

    # 6. Determinar nivel de riesgo global
    risk_level = _calculate_risk_level(file_risks, error_clusters, tech_debt_trends)

    # Estadisticas generales
    stats = {
        "total_delegations": global_data.get("total_delegations", 0),
        "files_scanned": len(file_risks) if project_root else 0,
        "errors_analyzed": len(error_log),
        "project_name": store_data.get("project_name", "unknown"),
    }

    return HealthReport(
        generated_at=datetime.now().isoformat(),
        project_name=store_data.get("project_name", "unknown"),
        risk_level=risk_level,
        file_risks=file_risks,
        error_clusters=error_clusters,
        tech_debt_trends=tech_debt_trends,
        recommendations=recommendations,
        stats=stats,
    )


def _predict_file_risks(project_root: str, line_limit: int) -> List[FileRisk]:
    """Escanea archivos de codigo y detecta los que estan cerca del limite."""
    risks = []
    extensions = {".py", ".ts", ".js", ".tsx", ".jsx"}
    threshold_warning = 0.75  # 75% del limite
    threshold_critical = 0.90  # 90% del limite

    for dirpath, _dirnames, filenames in os.walk(project_root):
        # Saltar directorios irrelevantes
        rel = os.path.relpath(dirpath, project_root)
        if any(skip in rel for skip in ["node_modules", ".git", "__pycache__", "dist", "build"]):
            continue

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in extensions:
                continue

            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    line_count = sum(1 for _ in f)
            except (IOError, OSError):
                continue

            pct = line_count / line_limit if line_limit > 0 else 0
            if pct >= threshold_warning:
                risk_level = "critical" if pct >= threshold_critical else "warning"
                rel_path = os.path.relpath(fpath, project_root)
                risks.append(FileRisk(
                    path=rel_path,
                    current_lines=line_count,
                    limit=line_limit,
                    percentage=pct,
                    risk_level=risk_level,
                ))

    # Ordenar por peligrosidad descendente
    risks.sort(key=lambda r: r.percentage, reverse=True)
    return risks[:20]  # Top 20 mas peligrosos


def _identify_error_clusters(error_log: list) -> List[ErrorCluster]:
    """Agrupa errores por tipo y detecta patrones recurrentes."""
    if not error_log:
        return []

    # Contar errores por tipo
    type_counts: dict = {}
    for entry in error_log:
        etype = entry.get("type", entry.get("error_type", "unknown"))
        if etype not in type_counts:
            type_counts[etype] = {"total": 0, "recent": 0, "examples": []}
        type_counts[etype]["total"] += 1
        if len(type_counts[etype]["examples"]) < 3:
            desc = entry.get("description", entry.get("message", ""))
            if desc:
                type_counts[etype]["examples"].append(desc[:100])

    # Contar recientes (ultimos 10 registros)
    recent = error_log[-10:] if len(error_log) > 10 else error_log
    for entry in recent:
        etype = entry.get("type", entry.get("error_type", "unknown"))
        if etype in type_counts:
            type_counts[etype]["recent"] += 1

    # Detectar tendencia (mas en recientes = increasing)
    clusters = []
    for etype, data in type_counts.items():
        if data["total"] < 2:
            continue  # Solo clusters de 2+

        recent_rate = data["recent"] / min(10, len(error_log))
        total_rate = data["total"] / len(error_log)

        if recent_rate > total_rate * 1.3:
            trend = "increasing"
        elif recent_rate < total_rate * 0.7:
            trend = "decreasing"
        else:
            trend = "stable"

        clusters.append(ErrorCluster(
            error_type=etype,
            count=data["total"],
            recent_count=data["recent"],
            trend=trend,
            examples=data["examples"],
        ))

    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters[:10]


def _detect_tech_debt_trends(
    delegation_history: list,
    error_log: list,
) -> List[TechDebtTrend]:
    """Detecta tendencias de deuda tecnica desde historial de delegaciones."""
    trends = []

    if not delegation_history:
        return trends

    # 1. Tasa de truncamiento
    truncations = sum(1 for d in delegation_history if not d.get("success", True))
    total = len(delegation_history)
    if total >= 3:
        trunc_rate = truncations / total
        if trunc_rate > 0.3:  # Mas del 30% falla
            trends.append(TechDebtTrend(
                indicator="failure_rate",
                description=f"Tasa de fallo alta: {truncations}/{total} delegaciones fallan",
                severity="high" if trunc_rate > 0.5 else "medium",
                value=trunc_rate,
                threshold=0.3,
            ))

    # 2. Tendencia de duracion creciente
    if len(delegation_history) >= 5:
        durations = [d.get("duration_s", 0) for d in delegation_history if d.get("duration_s")]
        if len(durations) >= 5:
            first_half = sum(durations[:len(durations)//2]) / (len(durations)//2)
            second_half = sum(durations[len(durations)//2:]) / (len(durations) - len(durations)//2)
            if second_half > first_half * 1.5 and first_half > 0:
                trends.append(TechDebtTrend(
                    indicator="duration_increase",
                    description="Duracion de delegaciones creciendo (posible complejidad acumulada)",
                    severity="medium",
                    value=second_half / first_half,
                    threshold=1.5,
                ))

    # 3. Errores repetitivos del mismo tipo
    if error_log:
        recent_errors = error_log[-10:]
        error_types = [e.get("type", "unknown") for e in recent_errors]
        for etype in set(error_types):
            count = error_types.count(etype)
            if count >= 3:  # 3+ del mismo tipo en ultimos 10
                trends.append(TechDebtTrend(
                    indicator="repeated_error",
                    description=f"Error '{etype}' aparece {count}/10 veces recientes — necesita fix sistematico",
                    severity="high" if count >= 5 else "medium",
                    value=count / 10,
                    threshold=0.3,
                ))

    return trends


def _detect_cross_project_trends(cross_errors: list) -> List[TechDebtTrend]:
    """Detecta tendencias que se repiten entre proyectos."""
    trends = []
    for err in cross_errors:
        projects = err.get("projects", [])
        if len(projects) >= 2 and err.get("count", 0) >= 3:
            trends.append(TechDebtTrend(
                indicator="cross_project_error",
                description=f"Error '{err.get('type', '?')}' se repite en {len(projects)} proyectos",
                severity="medium",
                value=err.get("count", 0),
                threshold=3,
            ))
    return trends[:5]


def _generate_recommendations(
    file_risks: List[FileRisk],
    error_clusters: List[ErrorCluster],
    tech_debt_trends: List[TechDebtTrend],
) -> List[str]:
    """Genera recomendaciones accionables priorizadas."""
    recs = []

    # Archivos criticos
    critical_files = [f for f in file_risks if f.risk_level == "critical"]
    if critical_files:
        names = ", ".join(f.path for f in critical_files[:3])
        recs.append(
            f"URGENTE: {len(critical_files)} archivo(s) al >90% del limite de lineas: {names}. "
            "Dividir en modulos helper inmediatamente."
        )

    warning_files = [f for f in file_risks if f.risk_level == "warning"]
    if warning_files:
        recs.append(
            f"ATENCION: {len(warning_files)} archivo(s) al 75-90% del limite. "
            "Planificar division antes de agregar features."
        )

    # Errores crecientes
    increasing = [c for c in error_clusters if c.trend == "increasing"]
    for cluster in increasing[:3]:
        recs.append(
            f"Error '{cluster.error_type}' esta AUMENTANDO ({cluster.recent_count} recientes). "
            "Investigar causa raiz y agregar regla preventiva."
        )

    # Tech debt trends
    for trend in tech_debt_trends:
        if trend.severity == "high":
            recs.append(f"DEUDA TECNICA: {trend.description}")

    # Recomendacion positiva si todo esta bien
    if not recs:
        recs.append("Proyecto saludable. Sin riesgos criticos detectados.")

    return recs[:10]


def _calculate_risk_level(
    file_risks: List[FileRisk],
    error_clusters: List[ErrorCluster],
    trends: List[TechDebtTrend],
) -> str:
    """Calcula nivel de riesgo global del proyecto."""
    score = 0

    # Archivos criticos = +3, warning = +1
    score += sum(3 for f in file_risks if f.risk_level == "critical")
    score += sum(1 for f in file_risks if f.risk_level == "warning")

    # Error clusters crecientes = +2
    score += sum(2 for c in error_clusters if c.trend == "increasing")

    # Tech debt trends de alta severidad = +3
    score += sum(3 for t in trends if t.severity == "high")
    score += sum(1 for t in trends if t.severity == "medium")

    if score >= 8:
        return "critical"
    elif score >= 3:
        return "warning"
    return "healthy"
