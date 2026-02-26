"""Prompts especializados para el modo agente autonomo.

Contiene los system prompts para modo agente y modo delegacion (Claude Code).
El prompt de delegacion ahora es modular — se ensambla con solo los bloques
necesarios segun la tarea (ver prompt_builder.py para los bloques).
"""

from deepseek_code.client.prompt_builder import (
    assemble_delegate_prompt,
    DEEPSEEK_CODE_IDENTITY,
    DELEGATE_BASE, DELEGATE_CODE_RULES,
    DELEGATE_TODO, DELEGATE_QUANTUM, DELEGATE_GENERATION,
    DELEGATE_SURGICAL, DELEGATE_MULTI_FILE,
)


AGENT_SYSTEM_PROMPT = """Eres DeepSeek Code — un agente autonomo de programacion con acceso completo a herramientas del sistema.
Tu objetivo es completar la meta del usuario paso a paso, SIN esperar mas instrucciones.
Produces codigo de calidad PROFESIONAL — limpio, eficiente y bien estructurado.

CAPACIDADES ACTIVAS:
- Pensamiento profundo (Deep Thinking): ACTIVADO — usalo para razonar antes de codificar
- Busqueda en internet: ACTIVADO — busca documentacion, APIs, ejemplos actuales si necesitas
- Herramientas del sistema: lee archivos, crea archivos, ejecuta comandos, gestiona proyectos
- Puedes usar MULTIPLES herramientas en una sola respuesta (hasta 8 a la vez)
- Si necesitas crear un directorio antes de escribir archivos en el, usa make_directory primero

REGLAS DE EJECUCION:
1. Analiza la meta y planifica los pasos necesarios ANTES de actuar
2. Ejecuta acciones concretas usando las herramientas disponibles
3. Evalua el resultado antes de decidir el siguiente paso
4. Cuando termines TODOS los pasos, incluye la palabra COMPLETADO en tu respuesta
5. Si algo falla, adapta tu plan e intenta una alternativa
6. Escribe archivos COMPLETOS en una sola llamada a write_file — nunca parciales
7. NO describas lo que harias — HAZLO directamente con herramientas

REGLAS DE CODIGO — TU CODIGO DEBE SER PROFESIONAL:
1. ARQUITECTURA: Separa responsabilidades. Funciones pequenas y cohesivas (<30 lineas).
2. NOMBRES: Variables descriptivas en ingles (camelCase JS/TS, snake_case Python).
3. CONSTANTES: Extrae numeros magicos a constantes nombradas.
4. ERROR HANDLING: try/catch donde corresponda, validacion de inputs.
5. MODULARIDAD: Si > 200 lineas, dividir en modulos.
6. PATRONES: Usa patrones apropiados cuando la complejidad lo justifique.
7. TIPOS: Tipado estatico cuando el lenguaje lo soporte.
8. DOCUMENTACION: JSDoc/docstrings en funciones publicas. Comentarios solo "por que".
9. RENDIMIENTO: Evita O(n^2). Usa Sets/Maps para lookups.
10. SEGURIDAD: Nunca innerHTML, nunca SQL sin parametrizar.

FORMATO DE RESPUESTA:
- Explica brevemente que vas a hacer (1-3 lineas)
- Usa las herramientas para ejecutar la accion
- Al terminar, da un resumen claro de lo logrado

SEGURIDAD:
- NO elimines archivos a menos que la meta lo requiera explicitamente
- NO ejecutes comandos destructivos
- Si algo sale mal, reporta el error y adapta el plan

Responde siempre en espanol."""


# --- PROMPT PARA MODO DELEGACION (usado por Claude Code) ---
# Ahora modular: se ensambla con assemble_delegate_prompt() segun la tarea.
# DELEGATE_SYSTEM_PROMPT se mantiene como alias retrocompatible (todos los bloques).
DELEGATE_SYSTEM_PROMPT = assemble_delegate_prompt(
    has_template=True, is_quantum=True
)


def build_step_prompt(goal: str, step_num: int, previous_results: list) -> str:
    """Construye el prompt para un paso especifico del agente."""
    history = ""
    for i, result in enumerate(previous_results, 1):
        summary = result[:8000] + "..." if len(result) > 8000 else result
        history += f"\n--- Paso {i} ---\n{summary}\n"

    if history:
        return (
            f"META: {goal}\n\n"
            f"PASOS ANTERIORES:{history}\n"
            f"PASO ACTUAL: {step_num}\n"
            f"Basandote en los resultados anteriores, decide que hacer ahora. "
            f"Si ya completaste la meta, incluye COMPLETADO en tu respuesta con un resumen final."
        )
    else:
        return (
            f"META: {goal}\n\n"
            f"Este es el PRIMER paso. Analiza la meta, planifica y ejecuta la primera accion.\n"
            f"IMPORTANTE: Si la tarea es crear un archivo, escribelo COMPLETO con todas las "
            f"funcionalidades en UNA sola llamada a write_file. No hagas multiples escrituras parciales."
        )


def build_delegate_prompt(task: str, template: str = None, context: str = None, feedback: str = None) -> str:
    """Construye el prompt de usuario para modo delegacion de Claude Code.

    Args:
        task: Descripcion precisa de lo que debe hacer
        template: Codigo esqueleto con marcadores TODO (opcional)
        context: Codigo de referencia para que siga el estilo (opcional)
        feedback: Correccion de errores del intento anterior (opcional)
    """
    parts = [f"TAREA: {task}"]

    if feedback:
        parts.append(
            f"\nCORRECCION IMPORTANTE — Tu respuesta anterior tenia estos errores:\n{feedback}\n"
            "Corrige TODOS estos errores. Tu jefe (Claude Code) revisa tu codigo."
        )

    if context:
        parts.append(f"\nCONTEXTO/ESTILO DE REFERENCIA:\n{context}")

    if template:
        parts.append(
            f"\nTEMPLATE A COMPLETAR (rellena SOLO los marcadores TODO):\n{template}"
        )
        parts.append(
            "\nResponde SOLO con las funciones/datos que reemplazan cada TODO. "
            "NO repitas el codigo del template. Formato:\n"
            "// === TODO X: nombre ===\n"
            "function nombre() { ... }\n"
            "Esto evita que tu respuesta se trunque."
        )
    else:
        parts.append(
            "\nResponde UNICAMENTE con el codigo solicitado. "
            "Sin explicaciones, sin markdown, sin bloques de codigo."
        )

    return "\n".join(parts)
