"""Funciones auxiliares para el merge de respuestas duales.

Extraccion de bloques TODO, funciones, variables, y validacion
de codigo fusionado. Usado por merge_engine.py.
"""

import re
from typing import Dict, List, Tuple


def extract_todo_blocks(response: str) -> Dict[str, str]:
    """Extrae bloques de codigo agrupados por marcador TODO.

    Busca patrones como:
      // === TODO 1A: renderPlayer(ctx) ===
      ...codigo...
      // === TODO 1B: updateEnemies() ===

    Returns:
        Dict con nombre_todo -> bloque_codigo
    """
    blocks = {}
    pattern = re.compile(
        r'//\s*={2,}\s*TODO\s+[\dA-Za-z]+\s*:\s*(\w+)',
        re.MULTILINE
    )
    matches = list(pattern.finditer(response))

    if not matches:
        return blocks

    for i, match in enumerate(matches):
        name = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(response)
        block = response[start:end].strip()
        blocks[name] = block

    return blocks


def extract_functions(response: str) -> Dict[str, str]:
    """Extrae funciones completas con su cuerpo del codigo.

    Soporta: function nombre() { ... }
    Detecta cierre de llaves por conteo.

    Returns:
        Dict con nombre_funcion -> codigo_completo
    """
    functions = {}
    lines = response.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]
        match = re.match(r'^(?:async\s+)?function\s+(\w+)\s*\(', line)

        if match:
            func_name = match.group(1)
            brace_count = 0
            found_open = False
            func_lines = []

            for j in range(i, min(i + 300, len(lines))):
                func_lines.append(lines[j])
                for ch in lines[j]:
                    if ch == '{':
                        brace_count += 1
                        found_open = True
                    elif ch == '}':
                        brace_count -= 1

                if found_open and brace_count <= 0:
                    break

            functions[func_name] = '\n'.join(func_lines)
            i += len(func_lines)
        else:
            i += 1

    return functions


def extract_variable_declarations(response: str) -> Dict[str, str]:
    """Extrae declaraciones top-level de variables/constantes.

    Busca: let NOMBRE = valor; o let NOMBRE = { ... };
    Ignora variables dentro de funciones (solo top-level, indent 0).

    Returns:
        Dict con nombre_variable -> linea_completa
    """
    variables = {}
    lines = response.split('\n')
    inside_function = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Rastrear si estamos dentro de una funcion
        if re.match(r'^(?:async\s+)?function\s+\w+\s*\(', stripped):
            inside_function += 1
        for ch in stripped:
            if ch == '{':
                if inside_function > 0:
                    inside_function += 1
            elif ch == '}':
                if inside_function > 0:
                    inside_function -= 1

        # Solo capturar variables top-level (no indentadas, no en funciones)
        if inside_function > 0:
            continue
        if line and line[0] in (' ', '\t'):
            continue

        match = re.match(r'^(?:let|var)\s+(\w+)\s*=', line)
        if match:
            name = match.group(1)
            # Si es un objeto/array multi-linea, capturar hasta cierre
            if '{' in line or '[' in line:
                brace_count = 0
                var_lines = []
                for j in range(i, min(i + 100, len(lines))):
                    var_lines.append(lines[j])
                    for ch in lines[j]:
                        if ch in ('{', '['):
                            brace_count += 1
                        elif ch in ('}', ']'):
                            brace_count -= 1
                    if brace_count <= 0 and j > i:
                        break
                variables[name] = '\n'.join(var_lines)
            else:
                variables[name] = line

    return variables


def detect_duplicate_functions(
    funcs_a: Dict[str, str],
    funcs_b: Dict[str, str],
) -> List[str]:
    """Detecta funciones con el mismo nombre en ambas respuestas.

    Returns:
        Lista de nombres de funciones duplicadas
    """
    names_a = set(funcs_a.keys())
    names_b = set(funcs_b.keys())
    return sorted(names_a & names_b)


def pick_better_implementation(impl_a: str, impl_b: str) -> str:
    """Elige la mejor implementacion entre dos candidatas.

    Criterios de preferencia:
    1. Mayor numero de lineas (mas completa)
    2. Menos lineas vacias (mas densa)
    3. Menos comentarios sueltos (mas codigo real)

    Returns:
        La mejor implementacion
    """
    score_a = _score_implementation(impl_a)
    score_b = _score_implementation(impl_b)
    return impl_a if score_a >= score_b else impl_b


def _score_implementation(code: str) -> float:
    """Calcula un score de calidad para una implementacion.

    Criterios mejorados:
    - Lineas de codigo reales (peso alto)
    - Penalizacion por comentarios excesivos
    - Bonus por control flow (if/for/while = logica real)
    - Bonus por error handling (try/catch)
    - Bonus por validacion (checks de input)
    - Penalizacion por lineas muy largas (>120 chars = posible concat)
    """
    lines = code.strip().split('\n')
    total = len(lines)
    if total == 0:
        return 0.0

    non_empty = sum(1 for l in lines if l.strip())
    comment_only = sum(1 for l in lines if l.strip().startswith('//'))
    code_lines = non_empty - comment_only

    # Bonus: logica real (control flow)
    control_flow = sum(1 for l in lines if re.search(
        r'\b(if|else|for|while|switch|case)\b', l
    ))
    # Bonus: error handling
    error_handling = sum(1 for l in lines if re.search(
        r'\b(try|catch|throw|Error)\b', l
    ))
    # Bonus: validacion de inputs
    validation = sum(1 for l in lines if re.search(
        r'(Math\.(min|max|floor|ceil)|\.length|typeof|===|!==)', l
    ))
    # Penalizacion: lineas demasiado largas (probable codigo comprimido)
    long_lines = sum(1 for l in lines if len(l) > 120)

    score = (
        code_lines
        + (non_empty * 0.1)
        - (comment_only * 0.05)
        + (control_flow * 0.3)
        + (error_handling * 0.5)
        + (validation * 0.2)
        - (long_lines * 0.1)
    )
    return score


def validate_braces(code: str) -> Tuple[bool, int]:
    """Verifica que las llaves esten balanceadas en el codigo.

    Returns:
        Tupla (balanceado: bool, diferencia: int)
        diferencia > 0 = llaves abiertas sin cerrar
        diferencia < 0 = llaves cerradas de mas
    """
    opens = code.count('{')
    closes = code.count('}')
    diff = opens - closes
    return diff == 0, diff


def validate_parentheses(code: str) -> Tuple[bool, int]:
    """Verifica que los parentesis esten balanceados.

    Returns:
        Tupla (balanceado: bool, diferencia: int)
    """
    opens = code.count('(')
    closes = code.count(')')
    diff = opens - closes
    return diff == 0, diff


def deduplicate_lines(text: str) -> str:
    """Elimina bloques y lineas duplicadas.

    Fase 1: Elimina declaraciones de variables duplicadas
            (let X = ...; que aparecen mas de una vez).
    Fase 2: Elimina bloques de 3+ lineas identicas consecutivas.
    """
    lines = text.split('\n')
    if len(lines) < 4:
        return text

    # Fase 1: Deduplica declaraciones de variables (let/var X = ...)
    seen_vars = {}  # nombre -> indice de primera aparicion
    skip_lines = set()

    for i, line in enumerate(lines):
        match = re.match(r'^(?:let|var)\s+(\w+)\s*=', line.strip())
        if match:
            name = match.group(1)
            if name in seen_vars:
                # Variable duplicada: calcular rango de lineas a saltar
                # Si es multi-linea (objeto/array), saltar hasta cierre
                j = i
                brace_count = 0
                while j < len(lines):
                    for ch in lines[j]:
                        if ch in ('{', '['):
                            brace_count += 1
                        elif ch in ('}', ']'):
                            brace_count -= 1
                    skip_lines.add(j)
                    j += 1
                    if brace_count <= 0 and j > i + 1:
                        break
                    if ';' in lines[i] and brace_count == 0:
                        break
            else:
                seen_vars[name] = i

    if skip_lines:
        lines = [l for i, l in enumerate(lines) if i not in skip_lines]

    # Fase 2: Bloques repetidos consecutivos (3+ lineas)
    result = []
    i = 0
    while i < len(lines):
        found_dup = False
        for block_size in range(3, min(20, (len(lines) - i) // 2 + 1)):
            block_a = lines[i:i + block_size]
            block_b = lines[i + block_size:i + 2 * block_size]
            if block_a == block_b:
                result.extend(block_a)
                i += 2 * block_size
                found_dup = True
                break
        if not found_dup:
            result.append(lines[i])
            i += 1

    # Fase 3: Eliminar lineas vacias consecutivas (max 2)
    final = []
    empty_count = 0
    for line in result:
        if line.strip() == '':
            empty_count += 1
            if empty_count <= 2:
                final.append(line)
        else:
            empty_count = 0
            final.append(line)

    return '\n'.join(final)
