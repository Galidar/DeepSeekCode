"""Logger de ejecuciones del agente autonomo."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class AgentLogger:
    """Registra las acciones del agente en archivos JSON."""

    def __init__(self, logs_dir: str):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save(self, goal: str, steps: list, status: str,
             summary: str, duration_s: float, error: Optional[str] = None) -> str:
        """Guarda el resultado de una ejecucion. Retorna la ruta del archivo."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"agent_{timestamp}.json"
        filepath = self.logs_dir / filename

        data = {
            "goal": goal,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "duration_s": round(duration_s, 2),
            "total_steps": len(steps),
            "steps": steps,
            "summary": summary,
            "error": error
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(filepath)
