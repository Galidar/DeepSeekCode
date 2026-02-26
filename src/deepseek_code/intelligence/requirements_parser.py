"""Requirements Pipeline — De documento de requisitos a plan multi-paso.

Parsea documentos de requisitos (Markdown, texto plano) y genera
planes de ejecucion compatibles con multi_step.py.

Soporta:
- Encabezados como features (# Feature 1: Login)
- Listas como sub-requisitos
- Prioridades (MUST, SHOULD, COULD)
- Dependencias entre requisitos ("depende de", "requires", "after")
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Requirement:
    """Requisito individual parseado del documento."""
    id: str
    description: str
    type: str = "feature"     # "feature", "constraint", "dependency", "task"
    priority: str = "should"  # "must", "should", "could"
    dependencies: List[str] = field(default_factory=list)
    sub_items: List[str] = field(default_factory=list)

    def estimated_complexity(self) -> int:
        """Estima complejidad basada en sub-items y largo."""
        base = 1
        base += len(self.sub_items)
        base += len(self.description) // 200
        return min(base, 10)


@dataclass
class ExecutionPlan:
    """Plan generado compatible con multi_step.py."""
    steps: List[dict]
    total_estimated_tokens: int
    recommended_mode: str     # "sequential", "parallel_groups", "quantum"

    def to_multi_step_json(self) -> dict:
        """Convierte a formato JSON compatible con multi_step.py StepSpec."""
        return {"steps": self.steps}


# Patrones de prioridad
PRIORITY_PATTERNS = {
    "must": [r"\bMUST\b", r"\bREQUIRED\b", r"\bCRITICAL\b", r"\bESSENTIAL\b",
             r"\bOBLIGATORIO\b", r"\bCRITICO\b"],
    "should": [r"\bSHOULD\b", r"\bRECOMMENDED\b", r"\bIMPORTANT\b",
               r"\bIMPORTANTE\b", r"\bRECOMENDADO\b"],
    "could": [r"\bCOULD\b", r"\bOPTIONAL\b", r"\bNICE.TO.HAVE\b",
              r"\bOPCIONAL\b", r"\bDESEABLE\b"],
}

# Patrones de dependencia
DEPENDENCY_PATTERNS = [
    r"[Dd]epende de:?\s*(.+)",
    r"[Rr]equires?:?\s*(.+)",
    r"[Aa]fter:?\s*(.+)",
    r"[Pp]rerequisit[oe]s?:?\s*(.+)",
    r"[Nn]ecesita:?\s*(.+)",
]

# Patrones de tipo
TYPE_PATTERNS = {
    "constraint": [r"\bconstraint\b", r"\brestriction\b", r"\blimit\b",
                   r"\brestriccion\b", r"\blimite\b"],
    "dependency": [r"\bdependency\b", r"\bdependencia\b", r"\bexternal\b"],
    "task": [r"\btask\b", r"\btarea\b", r"\bfix\b", r"\bbug\b"],
}


def parse_requirements(content: str) -> List[Requirement]:
    """Parsea un documento de requisitos.

    Soporta formato Markdown (encabezados + listas) y texto plano numerado.

    Args:
        content: Contenido del documento

    Returns:
        Lista de Requirement parseados
    """
    if not content or not content.strip():
        return []

    # Detectar formato
    if re.search(r"^#{1,3}\s+", content, re.MULTILINE):
        return _parse_markdown_requirements(content)
    if re.search(r"^\d+\.\s+", content, re.MULTILINE):
        return _parse_numbered_requirements(content)

    # Fallback: tratar cada parrafo como requisito
    return _parse_paragraph_requirements(content)


def _parse_markdown_requirements(content: str) -> List[Requirement]:
    """Parsea formato Markdown con encabezados y listas."""
    requirements = []
    current_req = None
    req_counter = 0

    for line in content.split("\n"):
        stripped = line.strip()

        # Encabezado = nuevo requisito
        header_match = re.match(r"^(#{1,3})\s+(.+)", stripped)
        if header_match:
            if current_req:
                requirements.append(current_req)

            req_counter += 1
            title = header_match.group(2).strip()
            # Extraer ID si tiene formato "Feature 1: Login" o "#1 Login"
            id_match = re.match(r"(?:Feature|Req|#|Step)\s*(\d+):?\s*(.*)", title, re.I)
            if id_match:
                req_id = f"req_{id_match.group(1)}"
                desc = id_match.group(2) or title
            else:
                req_id = f"req_{req_counter}"
                desc = title

            current_req = Requirement(
                id=req_id,
                description=desc,
                priority=_detect_priority(title),
                type=_detect_type(title),
            )
            continue

        # Lista = sub-item del requisito actual
        list_match = re.match(r"^[-*]\s+(.+)", stripped)
        if list_match and current_req:
            item_text = list_match.group(1)

            # Verificar si es una dependencia
            dep = _extract_dependency(item_text)
            if dep:
                current_req.dependencies.extend(dep)
            else:
                current_req.sub_items.append(item_text)
                # Actualizar prioridad si el item tiene marcadores
                item_priority = _detect_priority(item_text)
                if item_priority == "must" and current_req.priority != "must":
                    current_req.priority = "must"
            continue

        # Texto libre = agregar a descripcion actual
        if stripped and current_req:
            dep = _extract_dependency(stripped)
            if dep:
                current_req.dependencies.extend(dep)
            elif not stripped.startswith("```"):
                current_req.description += f" {stripped}"

    # Agregar ultimo requisito
    if current_req:
        requirements.append(current_req)

    # Resolver dependencias por nombre
    _resolve_dependency_names(requirements)

    return requirements


def _parse_numbered_requirements(content: str) -> List[Requirement]:
    """Parsea texto plano con numeracion (1. Feature, 2. Feature)."""
    requirements = []
    for match in re.finditer(r"(\d+)\.\s+(.+?)(?=\n\d+\.|\Z)", content, re.DOTALL):
        num = match.group(1)
        text = match.group(2).strip()
        lines = text.split("\n")
        desc = lines[0].strip()

        req = Requirement(
            id=f"req_{num}",
            description=desc,
            priority=_detect_priority(text),
            type=_detect_type(text),
        )

        # Sub-items de lineas subsecuentes
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith(("-", "*")):
                item = stripped.lstrip("-* ")
                dep = _extract_dependency(item)
                if dep:
                    req.dependencies.extend(dep)
                else:
                    req.sub_items.append(item)
            elif stripped:
                dep = _extract_dependency(stripped)
                if dep:
                    req.dependencies.extend(dep)

        requirements.append(req)

    _resolve_dependency_names(requirements)
    return requirements


def _parse_paragraph_requirements(content: str) -> List[Requirement]:
    """Fallback: cada parrafo separado por linea vacia es un requisito."""
    paragraphs = re.split(r"\n\s*\n", content.strip())
    requirements = []

    for i, para in enumerate(paragraphs, 1):
        text = para.strip()
        if not text or len(text) < 10:
            continue
        requirements.append(Requirement(
            id=f"req_{i}",
            description=text[:5000],
            priority=_detect_priority(text),
            type=_detect_type(text),
        ))

    return requirements


def _detect_priority(text: str) -> str:
    """Detecta prioridad por palabras clave."""
    for priority, patterns in PRIORITY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return priority
    return "should"


def _detect_type(text: str) -> str:
    """Detecta tipo de requisito por palabras clave."""
    text_lower = text.lower()
    for rtype, patterns in TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return rtype
    return "feature"


def _extract_dependency(text: str) -> List[str]:
    """Extrae dependencias de una linea de texto."""
    for pattern in DEPENDENCY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            deps_text = match.group(1)
            # Separar por coma o "y"/"and"
            deps = re.split(r"[,;]|\band\b|\by\b", deps_text)
            return [d.strip().lower() for d in deps if d.strip()]
    return []


def _resolve_dependency_names(requirements: List[Requirement]):
    """Resuelve dependencias por nombre a IDs."""
    name_to_id = {}
    for req in requirements:
        name_to_id[req.description.lower()[:200]] = req.id
        # Tambien mapear numeros ("feature 1" -> req_1)
        num_match = re.search(r"\d+", req.id)
        if num_match:
            name_to_id[num_match.group()] = req.id

    for req in requirements:
        resolved = []
        for dep in req.dependencies:
            # Buscar por nombre parcial
            matched = False
            for name, rid in name_to_id.items():
                if dep in name or name in dep:
                    resolved.append(rid)
                    matched = True
                    break
            if not matched:
                # Buscar por numero
                num_match = re.search(r"\d+", dep)
                if num_match:
                    candidate = f"req_{num_match.group()}"
                    if any(r.id == candidate for r in requirements):
                        resolved.append(candidate)
        req.dependencies = list(set(resolved))


def generate_execution_plan(
    requirements: List[Requirement],
    project_context: dict = None,
    max_steps: int = 10,
) -> ExecutionPlan:
    """Genera plan multi-paso desde requisitos parseados.

    Ordena por dependencias (topological sort), agrupa independientes
    para ejecucion paralela, y estima tokens por paso.
    """
    if not requirements:
        return ExecutionPlan(steps=[], total_estimated_tokens=0, recommended_mode="sequential")

    # Ordenar respetando dependencias
    sorted_reqs = _topological_sort(requirements)

    # Limitar a max_steps
    sorted_reqs = sorted_reqs[:max_steps]

    # Generar steps compatibles con StepSpec
    steps = []
    total_tokens = 0

    for req in sorted_reqs:
        # Construir descripcion de tarea
        task_parts = [req.description]
        for sub in req.sub_items[:5]:
            task_parts.append(f"- {sub}")
        task = "\n".join(task_parts)

        step = {
            "id": req.id,
            "task": task,
            "context_from": req.dependencies,
            "max_retries": 1,
            "validate": True,
        }

        # Estimar tokens
        estimated = req.estimated_complexity() * 2000  # ~2K tokens por complejidad
        total_tokens += estimated

        steps.append(step)

    # Recomendar modo de ejecucion
    independent_count = sum(1 for r in sorted_reqs if not r.dependencies)
    if independent_count >= 3:
        mode = "parallel_groups"
    elif len(sorted_reqs) <= 2:
        mode = "quantum"
    else:
        mode = "sequential"

    return ExecutionPlan(
        steps=steps,
        total_estimated_tokens=total_tokens,
        recommended_mode=mode,
    )


def _topological_sort(requirements: List[Requirement]) -> List[Requirement]:
    """Ordena requisitos respetando dependencias (topological sort)."""
    id_map = {r.id: r for r in requirements}
    visited = set()
    result = []
    visiting = set()  # Detectar ciclos

    def visit(req_id: str):
        if req_id in visited:
            return
        if req_id in visiting:
            return  # Ciclo detectado, ignorar
        visiting.add(req_id)

        req = id_map.get(req_id)
        if req:
            for dep_id in req.dependencies:
                if dep_id in id_map:
                    visit(dep_id)

        visiting.discard(req_id)
        visited.add(req_id)
        if req:
            result.append(req)

    # Priorizar por prioridad (must primero)
    priority_order = {"must": 0, "should": 1, "could": 2}
    sorted_reqs = sorted(requirements, key=lambda r: priority_order.get(r.priority, 1))

    for req in sorted_reqs:
        visit(req.id)

    return result
