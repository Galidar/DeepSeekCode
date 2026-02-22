"""Fachada fail-safe del Intelligence Package.

Punto unico de entrada para conectar las 5 features de inteligencia
con el flujo de delegacion existente. Todas las funciones son fail-safe:
si algo falla, retornan valores vacios sin romper el flujo principal.

Hooks disponibles:
- on_delegation_failure(): Cuando una delegacion falla (introspective debugging)
- on_post_commit(): Despues de que el usuario commitea (shadow learning)
- get_intelligence_briefing(): Para inyectar en system prompt
- generate_project_health(): Para health reports
"""

import os
import sys
import traceback
from typing import Optional


def on_delegation_failure(
    appdata_dir: str,
    task: str,
    validation: dict,
    response: str,
    store_data: Optional[dict] = None,
    global_data: Optional[dict] = None,
) -> dict:
    """Hook que se ejecuta cuando una delegacion falla.

    Invoca el Introspective Debugger para analisis profundo de causa raiz
    y retorna feedback mejorado para el retry.

    Returns:
        Dict con {analysis: dict, enhanced_feedback: str} o {} si falla
    """
    try:
        from deepseek_code.intelligence.debugger import (
            analyze_failure,
            build_enhanced_feedback,
        )

        analysis = analyze_failure(
            store_data=store_data,
            global_data=global_data,
            task=task,
            validation=validation,
            response=response,
        )

        enhanced_feedback = build_enhanced_feedback(analysis, validation)

        return {
            "analysis": analysis.to_dict(),
            "enhanced_feedback": enhanced_feedback,
        }
    except Exception as e:
        print(f"  [intel] Debugger error (fail-safe): {e}", file=sys.stderr)
        return {}


def on_post_commit(
    appdata_dir: str,
    project_root: str,
    last_delegation_response: str,
    surgical_store=None,
) -> list:
    """Hook que se ejecuta despues de que el usuario hace commit.

    Invoca Shadow Learning para detectar correcciones del usuario
    y alimentar SurgicalMemory con patrones aprendidos.

    Args:
        appdata_dir: Directorio de datos de la app
        project_root: Ruta raiz del proyecto (con .git)
        last_delegation_response: Respuesta de DeepSeek de la ultima delegacion
        surgical_store: Instancia de SurgicalStore (opcional)

    Returns:
        Lista de correcciones aprendidas, o [] si falla
    """
    try:
        from deepseek_code.intelligence.shadow_learner import (
            learn_from_user_corrections,
        )

        corrections = learn_from_user_corrections(
            project_root=project_root,
            last_delegation_response=last_delegation_response,
            max_commits_to_check=3,
        )

        # Si tenemos store, guardar las correcciones
        if surgical_store and corrections:
            for correction in corrections:
                try:
                    surgical_store.add_shadow_correction(correction.to_dict())
                except Exception:
                    pass
            try:
                surgical_store.save()
            except Exception:
                pass

        return corrections
    except Exception as e:
        print(f"  [intel] Shadow learner error (fail-safe): {e}", file=sys.stderr)
        return []


def get_intelligence_briefing(
    store_data: Optional[dict] = None,
    token_budget: int = 500,
) -> str:
    """Construye briefing compacto con datos del Intelligence Package.

    Incluye:
    - Shadow corrections aprendidas (top 5 por frecuencia)
    - Failure analyses recientes (top 3 por relevancia)
    - Reglas de prevencion activas

    Se inyecta junto con surgical_briefing y global_briefing.

    Returns:
        String con briefing formateado, o "" si no hay datos
    """
    try:
        if not store_data:
            return ""

        sections = []

        # Shadow corrections
        corrections = store_data.get("shadow_corrections", [])
        significant = [c for c in corrections if c.get("frequency", 0) >= 2]
        if significant:
            significant.sort(key=lambda x: x.get("frequency", 0), reverse=True)
            lines = ["CORRECCIONES APRENDIDAS DEL USUARIO:"]
            for c in significant[:5]:
                freq = c.get("frequency", 0)
                desc = c.get("description", "sin descripcion")
                lines.append(f"  [{freq}x] {desc}")
            sections.append("\n".join(lines))

        # Failure analyses recientes con reglas de prevencion
        analyses = store_data.get("failure_analyses", [])
        if analyses:
            recent = analyses[-3:]
            lines = ["ANALISIS DE FALLAS RECIENTES:"]
            for a in recent:
                pattern = a.get("pattern", "?")
                fix = a.get("fix_strategy", "?")
                lines.append(f"  - Patron: {pattern} -> Fix: {fix}")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        # Estimar tokens y truncar si necesario
        result = "\n\n".join(sections) + "\n"
        estimated_tokens = len(result) // 4
        if estimated_tokens > token_budget:
            max_chars = token_budget * 4
            result = result[:max_chars] + "\n[... truncado ...]\n"

        return result
    except Exception:
        return ""


def generate_project_health(
    appdata_dir: str,
    project_root: Optional[str] = None,
    store_data: Optional[dict] = None,
    global_data: Optional[dict] = None,
) -> dict:
    """Genera reporte de salud predictivo (wrapper fail-safe).

    Returns:
        HealthReport.to_dict() o {} si falla
    """
    try:
        from deepseek_code.intelligence.predictor import generate_health_report

        report = generate_health_report(
            store_data=store_data,
            global_data=global_data,
            project_root=project_root,
            line_limit=400,
        )
        return report.to_dict()
    except Exception as e:
        print(f"  [intel] Predictor error (fail-safe): {e}", file=sys.stderr)
        return {}
