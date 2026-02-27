"""Motor de fusion de respuestas duales para QuantumBridge.

Combina las respuestas de dos angulos complementarios en una sola
respuesta coherente. Usa tres estrategias de merge en cascada:
1. Template-guided (por bloques TODO)
2. Function-based (por funciones extraidas)
3. Raw concatenation (fallback)
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .merge_helpers import (
    extract_todo_blocks, extract_functions, extract_classes,
    extract_variable_declarations,
    detect_duplicate_functions, pick_better_implementation,
    validate_braces, validate_parentheses, deduplicate_lines,
)


@dataclass
class MergeResult:
    """Resultado de la fusion de dos respuestas."""
    merged: str
    success: bool
    strategy: str
    conflicts: List[str] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "strategy": self.strategy,
            "conflicts": self.conflicts,
            "stats": self.stats,
            "merged_chars": len(self.merged),
        }


def merge_responses(
    response_a: str,
    response_b: str,
    template: str = None,
    angle_a_label: str = "A",
    angle_b_label: str = "B",
) -> MergeResult:
    """Fusiona dos respuestas complementarias.

    Intenta tres estrategias en cascada:
    1. Si hay template: merge guiado por bloques TODO
    2. Si hay funciones: merge por extraccion de funciones
    3. Fallback: concatenacion inteligente

    Args:
        response_a: Respuesta del angulo A
        response_b: Respuesta del angulo B
        template: Template original con TODOs (opcional)
        angle_a_label: Etiqueta del angulo A
        angle_b_label: Etiqueta del angulo B

    Returns:
        MergeResult con el codigo fusionado
    """
    # Limpiar markdown si la respuesta viene envuelta en ```
    clean_a = _strip_markdown_fences(response_a)
    clean_b = _strip_markdown_fences(response_b)

    # Estrategia 1: Template-guided
    if template:
        result = _merge_by_todos(clean_a, clean_b, template)
        if result.success:
            return result

    # Estrategia 2: Function-based
    result = _merge_by_functions(clean_a, clean_b)
    if result.success:
        return result

    # Estrategia 3: Raw concatenation
    return _merge_raw(clean_a, clean_b, angle_a_label, angle_b_label)


def _strip_markdown_fences(text: str) -> str:
    """Elimina bloques ```javascript ... ``` del texto."""
    # Quitar primer bloque de apertura
    text = re.sub(r'^```\w*\n?', '', text.strip())
    # Quitar ultimo bloque de cierre
    text = re.sub(r'\n?```\s*$', '', text.strip())
    return text.strip()


def _merge_by_todos(
    response_a: str,
    response_b: str,
    template: str,
) -> MergeResult:
    """Estrategia 1: Merge guiado por bloques TODO del template.

    Extrae bloques TODO de ambas respuestas y los ordena segun
    el template original. Combina TODOs exclusivos de cada angulo
    y resuelve conflictos eligiendo la mejor implementacion.
    """
    blocks_a = extract_todo_blocks(response_a)
    blocks_b = extract_todo_blocks(response_b)

    if not blocks_a and not blocks_b:
        return MergeResult(merged="", success=False, strategy="todos_failed")

    # Extraer orden de TODOs del template
    from cli.delegate_validator import _extract_todos_from_template
    template_order = _extract_todos_from_template(template)

    merged_blocks = {}
    conflicts = []

    # Combinar bloques por nombre
    all_names = set(list(blocks_a.keys()) + list(blocks_b.keys()))
    for name in all_names:
        in_a = name in blocks_a
        in_b = name in blocks_b

        if in_a and in_b:
            # Conflicto: elegir la mejor implementacion
            better = pick_better_implementation(blocks_a[name], blocks_b[name])
            merged_blocks[name] = better
            conflicts.append(f"Duplicado '{name}': resuelto por score")
        elif in_a:
            merged_blocks[name] = blocks_a[name]
        else:
            merged_blocks[name] = blocks_b[name]

    # Ordenar segun template
    ordered_parts = []
    seen = set()

    for todo_name in template_order:
        if todo_name in merged_blocks:
            ordered_parts.append(merged_blocks[todo_name])
            seen.add(todo_name)

    # Agregar bloques que no estaban en el template
    for name, block in merged_blocks.items():
        if name not in seen:
            ordered_parts.append(block)

    merged = '\n\n'.join(ordered_parts)

    # Validar
    braces_ok, brace_diff = validate_braces(merged)
    parens_ok, paren_diff = validate_parentheses(merged)

    if not braces_ok:
        conflicts.append(f"Llaves desbalanceadas ({brace_diff:+d})")
    if not parens_ok:
        conflicts.append(f"Parentesis desbalanceados ({paren_diff:+d})")

    stats = {
        "blocks_from_a": len(blocks_a),
        "blocks_from_b": len(blocks_b),
        "total_merged": len(merged_blocks),
        "braces_balanced": braces_ok,
    }

    # Exito si tenemos al menos el 60% de los TODOs del template
    coverage = len(seen) / max(len(template_order), 1)
    success = coverage >= 0.6 and braces_ok
    stats["coverage"] = round(coverage, 2)

    return MergeResult(
        merged=merged,
        success=success,
        strategy="template_guided",
        conflicts=conflicts,
        stats=stats,
    )


def _merge_by_functions(
    response_a: str,
    response_b: str,
) -> MergeResult:
    """Estrategia 2: Merge por extraccion de funciones y clases.

    Extrae funciones, clases ES6 y variables de ambas respuestas,
    deduplica por nombre, y concatena en orden:
    variables primero, luego clases, luego funciones.
    """
    funcs_a = extract_functions(response_a)
    funcs_b = extract_functions(response_b)
    classes_a = extract_classes(response_a)
    classes_b = extract_classes(response_b)
    vars_a = extract_variable_declarations(response_a)
    vars_b = extract_variable_declarations(response_b)

    total_symbols = (
        len(funcs_a) + len(funcs_b)
        + len(classes_a) + len(classes_b)
        + len(vars_a) + len(vars_b)
    )
    if total_symbols < 2:
        return MergeResult(merged="", success=False, strategy="functions_failed")

    # Fusionar variables (sin duplicados, con conflictos reportados)
    merged_vars = {}
    var_conflicts = []
    for name, code in vars_a.items():
        merged_vars[name] = code
    for name, code in vars_b.items():
        if name not in merged_vars:
            merged_vars[name] = code
        else:
            merged_vars[name] = pick_better_implementation(merged_vars[name], code)
            var_conflicts.append(f"Variable duplicada: {name}")

    # Fusionar clases (resolver duplicados)
    class_duplicates = detect_duplicate_functions(classes_a, classes_b)
    conflicts = [f"Clase duplicada: {d}" for d in class_duplicates]

    merged_classes = {}
    for name, code in classes_a.items():
        merged_classes[name] = code
    for name, code in classes_b.items():
        if name not in merged_classes:
            merged_classes[name] = code
        else:
            merged_classes[name] = pick_better_implementation(merged_classes[name], code)

    # Fusionar funciones (resolver duplicados)
    func_duplicates = detect_duplicate_functions(funcs_a, funcs_b)
    conflicts.extend([f"Funcion duplicada: {d}" for d in func_duplicates])
    conflicts.extend(var_conflicts)

    merged_funcs = {}
    for name, code in funcs_a.items():
        merged_funcs[name] = code
    for name, code in funcs_b.items():
        if name not in merged_funcs:
            merged_funcs[name] = code
        else:
            merged_funcs[name] = pick_better_implementation(merged_funcs[name], code)

    # Componer: variables primero, luego clases, luego funciones
    parts = []
    for name, code in merged_vars.items():
        parts.append(code)
    if merged_vars and (merged_classes or merged_funcs):
        parts.append("")  # Separador
    for name, code in merged_classes.items():
        parts.append(code)
    if merged_classes and merged_funcs:
        parts.append("")  # Separador
    for name, code in merged_funcs.items():
        parts.append(code)

    merged = '\n\n'.join(parts)
    merged = deduplicate_lines(merged)

    braces_ok, brace_diff = validate_braces(merged)

    let_total_merged = len(merged_funcs) + len(merged_classes)
    stats = {
        "functions_from_a": len(funcs_a),
        "functions_from_b": len(funcs_b),
        "classes_from_a": len(classes_a),
        "classes_from_b": len(classes_b),
        "vars_from_a": len(vars_a),
        "vars_from_b": len(vars_b),
        "func_duplicates_resolved": len(func_duplicates),
        "class_duplicates_resolved": len(class_duplicates),
        "var_duplicates_resolved": len(var_conflicts),
        "total_merged_funcs": len(merged_funcs),
        "total_merged_classes": len(merged_classes),
        "total_merged_vars": len(merged_vars),
        "braces_balanced": braces_ok,
    }

    # Exito si hay al menos 1 funcion/clase merged y braces OK
    success = braces_ok and let_total_merged >= 1

    return MergeResult(
        merged=merged,
        success=success,
        strategy="function_based",
        conflicts=conflicts,
        stats=stats,
    )


def _merge_raw(
    response_a: str,
    response_b: str,
    label_a: str = "A",
    label_b: str = "B",
) -> MergeResult:
    """Estrategia 3: Concatenacion inteligente (fallback).

    Concatena ambas respuestas con separador, elimina bloques
    duplicados consecutivos, y verifica balance de llaves.
    """
    # Concatenar con separador claro
    merged = (
        f"// ========== Angulo {label_a} ==========\n\n"
        f"{response_a}\n\n"
        f"// ========== Angulo {label_b} ==========\n\n"
        f"{response_b}"
    )

    merged = deduplicate_lines(merged)
    braces_ok, brace_diff = validate_braces(merged)

    stats = {
        "chars_a": len(response_a),
        "chars_b": len(response_b),
        "chars_merged": len(merged),
        "braces_balanced": braces_ok,
    }

    return MergeResult(
        merged=merged,
        success=True,  # Raw siempre "funciona" como fallback
        strategy="raw_concatenation",
        conflicts=[f"Llaves desbalanceadas ({brace_diff:+d})"] if not braces_ok else [],
        stats=stats,
    )
