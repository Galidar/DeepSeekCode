"""Deteccion automatica de angulos complementarios para delegacion dual.

Analiza la tarea y el template para dividir el trabajo en dos
perspectivas complementarias que se ejecutan en paralelo.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class AngleSpec:
    """Especificacion de un angulo/perspectiva de trabajo."""
    name: str
    label: str
    focus: str
    system_extra: str = ""
    todos_filter: List[str] = field(default_factory=list)


# --- Pares de angulos predefinidos ---

ANGLE_PAIRS = {
    "game_full": {
        "description": "Juego completo: datos+logica vs UI+renderizado",
        "keywords": ["game", "juego", "shooter", "shmup", "plataformas", "rpg"],
        "angle_a": AngleSpec(
            name="logic_data",
            label="Logica y Datos",
            focus="datos, constantes, logica de juego, colisiones, spawning, estado",
            system_extra=(
                "Tu responsabilidad: SOLO las funciones de DATOS y LOGICA.\n"
                "Incluye: constantes/objetos de configuracion, funciones de inicializacion, "
                "logica de colisiones, spawning de entidades, actualizacion de estado, "
                "funciones de utilidad matematica.\n"
                "NO implementes: funciones de dibujo/render, efectos visuales, HUD, "
                "particulas, ni nada que use ctx.fillRect/drawImage/stroke."
            ),
        ),
        "angle_b": AngleSpec(
            name="ui_render",
            label="UI y Renderizado",
            focus="renderizado, dibujo, efectos visuales, HUD, particulas, audio",
            system_extra=(
                "Tu responsabilidad: SOLO las funciones de RENDERIZADO y UI.\n"
                "Incluye: funciones de dibujo (draw*), efectos visuales, particulas, "
                "HUD/interfaz, animaciones, audio, game loop principal.\n"
                "NO implementes: constantes de datos, logica de colisiones, spawning, "
                "ni funciones de utilidad que no dibujen. "
                "ASUME que las funciones de logica ya existen y usalas por nombre."
            ),
        ),
    },
    "fullstack": {
        "description": "Fullstack: backend vs frontend",
        "keywords": ["fullstack", "servidor", "server", "api", "frontend", "backend"],
        "angle_a": AngleSpec(
            name="backend",
            label="Backend",
            focus="servidor, API endpoints, base de datos, logica de negocio",
            system_extra=(
                "Tu responsabilidad: SOLO el codigo del BACKEND.\n"
                "Incluye: endpoints API, modelos de datos, validacion, "
                "logica de negocio, middleware, autenticacion."
            ),
        ),
        "angle_b": AngleSpec(
            name="frontend",
            label="Frontend",
            focus="interfaz, componentes, estilos, interaccion de usuario",
            system_extra=(
                "Tu responsabilidad: SOLO el codigo del FRONTEND.\n"
                "Incluye: componentes UI, estilos, manejo de eventos, "
                "llamadas a API, estado del cliente, renderizado."
            ),
        ),
    },
    "refactor": {
        "description": "Refactor: estructura vs implementacion",
        "keywords": ["refactor", "refactorizar", "reestructurar", "optimizar"],
        "angle_a": AngleSpec(
            name="structure",
            label="Estructura",
            focus="tipos, interfaces, modulos, organizacion de archivos",
            system_extra=(
                "Tu responsabilidad: ESTRUCTURA del codigo.\n"
                "Incluye: definir tipos/interfaces, organizar modulos, "
                "establecer imports, crear esqueletos de clases/funciones."
            ),
        ),
        "angle_b": AngleSpec(
            name="implementation",
            label="Implementacion",
            focus="logica interna, algoritmos, optimizacion de funciones",
            system_extra=(
                "Tu responsabilidad: IMPLEMENTACION interna.\n"
                "Incluye: cuerpo de funciones, algoritmos, optimizaciones, "
                "manejo de errores, logica de negocio detallada."
            ),
        ),
    },
    "template_split": {
        "description": "Split por TODOs: primera mitad vs segunda mitad",
        "keywords": [],  # Se activa automaticamente por tamaño de template
        "angle_a": AngleSpec(
            name="todos_first_half",
            label="TODOs (primera mitad)",
            focus="primera mitad de las funciones/TODOs del template",
        ),
        "angle_b": AngleSpec(
            name="todos_second_half",
            label="TODOs (segunda mitad)",
            focus="segunda mitad de las funciones/TODOs del template",
        ),
    },
}


def detect_angles(
    task: str,
    template: str = None,
) -> Tuple[AngleSpec, AngleSpec]:
    """Auto-detecta los angulos complementarios segun tarea y template.

    Estrategia:
    1. Si template tiene >8 TODOs, usa template_split con TODOs divididos
    2. Si keywords de la tarea matchean un par predefinido, usa ese
    3. Fallback: game_full (el caso mas comun de delegacion)

    Args:
        task: Descripcion de la tarea
        template: Template con TODOs (opcional)

    Returns:
        Tupla (angle_a, angle_b)
    """
    task_lower = task.lower()

    # Prioridad 1: Template grande -> split por TODOs
    if template:
        from cli.delegate_validator import estimate_template_tokens
        info = estimate_template_tokens(template)
        if info["recommended_split"] and info["suggested_splits"]:
            return _build_template_split_angles(info)

    # Prioridad 2: Keywords de la tarea
    for pair_name, pair_data in ANGLE_PAIRS.items():
        if pair_name == "template_split":
            continue  # Solo se activa por template grande
        keywords = pair_data["keywords"]
        if any(kw in task_lower for kw in keywords):
            return pair_data["angle_a"], pair_data["angle_b"]

    # Fallback: game_full
    return ANGLE_PAIRS["game_full"]["angle_a"], ANGLE_PAIRS["game_full"]["angle_b"]


def _build_template_split_angles(
    template_info: dict,
) -> Tuple[AngleSpec, AngleSpec]:
    """Construye angulos dividiendo TODOs del template en dos mitades.

    Args:
        template_info: Resultado de estimate_template_tokens()

    Returns:
        Tupla (angle_a, angle_b) con todos_filter configurados
    """
    splits = template_info["suggested_splits"]
    first_half = splits[0] if len(splits) > 0 else []
    second_half = splits[1] if len(splits) > 1 else []

    angle_a = AngleSpec(
        name="todos_first_half",
        label=f"TODOs 1-{len(first_half)}",
        focus=f"Implementar: {', '.join(first_half[:5])}{'...' if len(first_half) > 5 else ''}",
        system_extra=(
            f"Implementa SOLAMENTE estos TODOs: {', '.join(first_half)}\n"
            "NO implementes los demas TODOs del template. "
            "Para las funciones que NO te corresponden, deja el marcador TODO intacto."
        ),
        todos_filter=first_half,
    )

    angle_b = AngleSpec(
        name="todos_second_half",
        label=f"TODOs {len(first_half) + 1}-{len(first_half) + len(second_half)}",
        focus=f"Implementar: {', '.join(second_half[:5])}{'...' if len(second_half) > 5 else ''}",
        system_extra=(
            f"Implementa SOLAMENTE estos TODOs: {', '.join(second_half)}\n"
            "NO implementes los demas TODOs del template. "
            "Para las funciones que NO te corresponden, deja el marcador TODO intacto."
        ),
        todos_filter=second_half,
    )

    return angle_a, angle_b


def build_angle_system_prompt(
    base_system: str,
    angle: AngleSpec,
    task: str,
    template: str = None,
) -> str:
    """Enriquece el system prompt base con instrucciones del angulo.

    Args:
        base_system: DELEGATE_SYSTEM_PROMPT base
        angle: Especificacion del angulo
        task: Tarea original
        template: Template (opcional, para referencia)

    Returns:
        System prompt enriquecido
    """
    parts = [base_system]

    parts.append(f"\n\n== MODO QUANTUM: ANGULO '{angle.label.upper()}' ==")
    parts.append(f"Focus: {angle.focus}")

    if angle.system_extra:
        parts.append(f"\n{angle.system_extra}")

    if angle.todos_filter:
        parts.append(
            f"\nTODOs asignados a ti: {', '.join(angle.todos_filter)}"
        )

    parts.append(
        "\nIMPORTANTE: Tu respuesta sera FUSIONADA con la de otro angulo. "
        "Asegurate de que tu codigo sea modular y las funciones tengan "
        "nombres claros para facilitar la fusion."
    )
    parts.append("== FIN INSTRUCCIONES QUANTUM ==\n")

    return '\n'.join(parts)


def build_manual_angles(name_a: str, name_b: str) -> Tuple[AngleSpec, AngleSpec]:
    """Crea angulos personalizados por nombre.

    Args:
        name_a: Nombre/focus del angulo A
        name_b: Nombre/focus del angulo B

    Returns:
        Tupla (angle_a, angle_b)
    """
    angle_a = AngleSpec(
        name=_slugify(name_a),
        label=name_a,
        focus=name_a,
        system_extra=f"Tu responsabilidad: {name_a}. Implementa SOLO lo relacionado con este aspecto.",
    )
    angle_b = AngleSpec(
        name=_slugify(name_b),
        label=name_b,
        focus=name_b,
        system_extra=f"Tu responsabilidad: {name_b}. Implementa SOLO lo relacionado con este aspecto.",
    )
    return angle_a, angle_b


def _slugify(text: str) -> str:
    """Convierte texto a slug para usar como identificador."""
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower().strip())
    return slug.strip('_')[:40]
