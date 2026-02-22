"""CLI Runners para el Intelligence Package.

Dos modos programaticos:
1. --requirements doc.md [--auto-execute] [--json]
   Parsea documento de requisitos y genera/ejecuta plan multi-paso

2. --health-report [--project-context CLAUDE.md] [--json]
   Genera reporte predictivo de salud del proyecto

Ambos siguen el patron de bridge_utils (redirect_output, output_json).
"""

import json
import os
import sys
import time

from cli.bridge_utils import (
    redirect_output,
    restore_output,
    output_json,
    output_text,
    load_file_safe,
)
from cli.config_loader import load_config, APPDATA_DIR


def run_requirements(
    requirements_path: str,
    json_mode: bool = False,
    config_path: str = None,
    auto_execute: bool = False,
):
    """Parsea requisitos y genera (opcionalmente ejecuta) plan multi-paso.

    Flujo:
    1. Leer documento de requisitos
    2. Parsear a lista de Requirement
    3. Generar ExecutionPlan (compatible con multi_step.py)
    4. Si auto_execute: ejecutar con run_multi_step()
    5. Output como JSON o texto

    Args:
        requirements_path: Ruta al .md o .txt con requisitos
        json_mode: True para output JSON
        config_path: Ruta al config (opcional)
        auto_execute: True para ejecutar el plan generado
    """
    originals = None
    try:
        if json_mode:
            originals = redirect_output()

        start_time = time.time()
        print(f"  [intel] Parseando requisitos: {requirements_path}", file=sys.stderr)

        # Leer documento
        content = load_file_safe(requirements_path, "Documento de requisitos")

        # Parsear requisitos
        from deepseek_code.intelligence.requirements_parser import (
            parse_requirements,
            generate_execution_plan,
        )

        requirements = parse_requirements(content)
        if not requirements:
            msg = "No se encontraron requisitos en el documento."
            if json_mode:
                restore_output(*originals)
                originals = None
                output_json({"success": False, "error": msg, "mode": "requirements"})
            else:
                print(msg, file=sys.stderr)
            return

        print(
            f"  [intel] Encontrados {len(requirements)} requisitos. Generando plan...",
            file=sys.stderr,
        )

        # Generar plan
        plan = generate_execution_plan(requirements)
        duration = time.time() - start_time

        print(
            f"  [intel] Plan generado: {len(plan.steps)} pasos, "
            f"modo recomendado: {plan.recommended_mode}",
            file=sys.stderr,
        )

        # Auto-execute si se pidio
        if auto_execute:
            print("  [intel] Auto-ejecutando plan con multi_step...", file=sys.stderr)
            plan_json = plan.to_multi_step_json()

            # Guardar plan temporal para multi_step
            plan_path = os.path.join(APPDATA_DIR, "_auto_requirements_plan.json")
            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(plan_json, f, ensure_ascii=False, indent=2)

            from cli.multi_step import run_multi_step
            # Restaurar output antes de delegar a multi_step
            if originals:
                restore_output(*originals)
                originals = None
            run_multi_step(
                plan_path=plan_path,
                json_mode=json_mode,
                config_path=config_path,
            )
            # Limpiar plan temporal
            try:
                os.remove(plan_path)
            except OSError:
                pass
            return

        # Output del plan (sin auto-execute)
        if json_mode:
            restore_output(*originals)
            originals = None
            result = {
                "success": True,
                "mode": "requirements",
                "requirements_count": len(requirements),
                "plan": plan.to_multi_step_json(),
                "recommended_mode": plan.recommended_mode,
                "estimated_tokens": plan.total_estimated_tokens,
                "duration_s": round(duration, 1),
                "requirements": [
                    {"id": r.id, "description": r.description,
                     "type": r.type, "priority": r.priority,
                     "dependencies": r.dependencies}
                    for r in requirements
                ],
            }
            output_json(result)
        else:
            _print_plan_text(requirements, plan)

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "requirements"})
        else:
            print(f"Error en requirements: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def run_health_report(
    json_mode: bool = False,
    config_path: str = None,
    project_path: str = None,
):
    """Genera reporte predictivo de salud del proyecto.

    Flujo:
    1. Cargar SurgicalStore + GlobalStore
    2. Detectar raiz del proyecto
    3. Generar HealthReport
    4. Output como JSON o texto

    Args:
        json_mode: True para output JSON
        config_path: Ruta al config (opcional)
        project_path: Ruta a CLAUDE.md o directorio del proyecto
    """
    originals = None
    try:
        if json_mode:
            originals = redirect_output()

        print("  [intel] Generando reporte de salud...", file=sys.stderr)
        start_time = time.time()

        # Detectar raiz del proyecto
        project_root = None
        if project_path:
            if os.path.isfile(project_path):
                project_root = os.path.dirname(os.path.abspath(project_path))
            else:
                project_root = os.path.abspath(project_path)
        else:
            # Intentar detectar desde CWD
            from deepseek_code.surgical.collector import detect_project_root
            project_root = detect_project_root(os.getcwd())

        # Cargar stores
        store_data = _load_surgical_data(project_root)
        global_data = _load_global_data()

        # Generar reporte
        from deepseek_code.intelligence.integration import generate_project_health

        report = generate_project_health(
            appdata_dir=APPDATA_DIR,
            project_root=project_root,
            store_data=store_data,
            global_data=global_data,
        )

        duration = time.time() - start_time

        if json_mode:
            restore_output(*originals)
            originals = None
            result = {
                "success": True,
                "mode": "health_report",
                "report": report,
                "duration_s": round(duration, 1),
            }
            output_json(result)
        else:
            _print_health_text(report)

    except Exception as e:
        if json_mode:
            if originals:
                restore_output(*originals)
                originals = None
            output_json({"success": False, "error": str(e), "mode": "health_report"})
        else:
            print(f"Error en health report: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if originals:
            restore_output(*originals)


def _load_surgical_data(project_root: str = None) -> dict:
    """Carga datos del SurgicalStore del proyecto (fail-safe)."""
    try:
        from deepseek_code.surgical.store import SurgicalStore
        store = SurgicalStore(APPDATA_DIR)
        if project_root:
            return store.load(project_root)
    except Exception:
        pass
    return {}


def _load_global_data() -> dict:
    """Carga datos del GlobalStore (fail-safe)."""
    try:
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(APPDATA_DIR)
        return store.load()
    except Exception:
        pass
    return {}


def _print_plan_text(requirements, plan):
    """Imprime plan de requisitos en formato legible."""
    print(f"\n{'='*60}")
    print(f"PLAN DE EJECUCION ({len(requirements)} requisitos -> {len(plan.steps)} pasos)")
    print(f"Modo recomendado: {plan.recommended_mode}")
    print(f"Tokens estimados: {plan.total_estimated_tokens:,}")
    print(f"{'='*60}\n")

    for i, step in enumerate(plan.steps, 1):
        task = step.get("task", "?")
        deps = step.get("context_from", [])
        dep_str = f" (depende de: {', '.join(deps)})" if deps else ""
        print(f"  Paso {i}: {task}{dep_str}")

    print(f"\n{'='*60}")
    print("Para ejecutar: agrega --auto-execute al comando")
    print(f"{'='*60}\n")


def _print_health_text(report: dict):
    """Imprime reporte de salud en formato legible."""
    risk = report.get("risk_level", "unknown")
    risk_emoji = {"healthy": "OK", "warning": "ATENCION", "critical": "CRITICO"}.get(risk, "?")

    print(f"\n{'='*60}")
    print(f"REPORTE DE SALUD DEL PROYECTO — [{risk_emoji}]")
    print(f"{'='*60}\n")

    # Archivos en riesgo
    file_risks = report.get("file_risks", [])
    if file_risks:
        print("ARCHIVOS EN RIESGO:")
        for f in file_risks[:10]:
            print(f"  [{f['risk']}] {f['path']}: {f['lines']}/{f['limit']} ({f['pct']}%)")
        print()

    # Clusters de errores
    clusters = report.get("error_clusters", [])
    if clusters:
        print("CLUSTERS DE ERRORES:")
        for c in clusters[:5]:
            print(f"  [{c['trend']}] {c['type']}: {c['count']} total, {c['recent']} recientes")
        print()

    # Tech debt
    trends = report.get("tech_debt_trends", [])
    if trends:
        print("TENDENCIAS DE DEUDA TECNICA:")
        for t in trends[:5]:
            print(f"  [{t['severity']}] {t['description']}")
        print()

    # Recomendaciones
    recs = report.get("recommendations", [])
    if recs:
        print("RECOMENDACIONES:")
        for i, r in enumerate(recs, 1):
            print(f"  {i}. {r}")
        print()

    print(f"{'='*60}\n")
