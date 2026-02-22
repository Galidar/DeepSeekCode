"""Roles predefinidos para sesiones multi-instancia.

Cada rol define un system prompt especializado y parametros de configuracion
para una instancia de DeepSeek dentro de una multi-sesion.

Roles disponibles:
    generator  — Genera codigo completo desde cero
    reviewer   — Revisa codigo y reporta issues
    tester     — Genera tests para el codigo
    specialist — Especialista en un dominio especifico
    merger     — Fusiona outputs de otros roles
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class RoleType(Enum):
    """Tipos de rol para instancias de DeepSeek."""
    GENERATOR = "generator"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SPECIALIST = "specialist"
    MERGER = "merger"


@dataclass
class SessionRole:
    """Definicion de un rol para una instancia de DeepSeek."""
    role_type: RoleType
    label: str
    system_suffix: str  # Se agrega al system prompt base
    max_steps: int = 10
    priority: int = 0  # Mayor = se ejecuta primero


# --- System prompt suffixes por rol ---
# Ultra-compactos: solo lo que diferencia al rol

GENERATOR_SUFFIX = (
    "\n\nROLE: GENERATOR\n"
    "You are the primary code generator. Create COMPLETE, functional code. "
    "Follow all TODO markers if a template is provided. "
    "Never leave stubs or placeholders."
)

REVIEWER_SUFFIX = (
    "\n\nROLE: REVIEWER\n"
    "You are reviewing code for correctness. "
    "List ONLY real bugs and issues (max 10). "
    "Format: ISSUE N: [file/function] description\n"
    "Do NOT suggest style changes. Focus on logic errors, "
    "missing implementations, and runtime failures."
)

TESTER_SUFFIX = (
    "\n\nROLE: TESTER\n"
    "You generate comprehensive tests for the given code. "
    "Cover edge cases, error paths, and integration points. "
    "Use the testing framework appropriate for the language."
)

SPECIALIST_SUFFIX = (
    "\n\nROLE: SPECIALIST\n"
    "You are a domain specialist. Focus on your area of expertise "
    "and provide the most technically accurate implementation possible. "
    "Your domain: {domain}"
)

MERGER_SUFFIX = (
    "\n\nROLE: MERGER\n"
    "You combine outputs from multiple code generators into one "
    "cohesive, complete implementation. Resolve conflicts by choosing "
    "the more complete or correct version. Output ONLY the final merged code."
)


def build_role(
    role_type: RoleType,
    label: str = "",
    domain: str = "",
    max_steps: int = 10,
) -> SessionRole:
    """Crea un SessionRole configurado.

    Args:
        role_type: Tipo de rol
        label: Etiqueta para logs (ej: "A", "B", "review")
        domain: Dominio para SPECIALIST (ej: "audio", "networking")
        max_steps: Maximo de pasos de tool-calling

    Returns:
        SessionRole configurado
    """
    suffixes = {
        RoleType.GENERATOR: GENERATOR_SUFFIX,
        RoleType.REVIEWER: REVIEWER_SUFFIX,
        RoleType.TESTER: TESTER_SUFFIX,
        RoleType.SPECIALIST: SPECIALIST_SUFFIX.replace("{domain}", domain),
        RoleType.MERGER: MERGER_SUFFIX,
    }

    priorities = {
        RoleType.GENERATOR: 10,
        RoleType.SPECIALIST: 8,
        RoleType.REVIEWER: 5,
        RoleType.TESTER: 5,
        RoleType.MERGER: 0,
    }

    if not label:
        label = role_type.value

    return SessionRole(
        role_type=role_type,
        label=label,
        system_suffix=suffixes.get(role_type, ""),
        max_steps=max_steps,
        priority=priorities.get(role_type, 0),
    )


# --- Presets de combinaciones de roles ---

def preset_generate_review() -> List[SessionRole]:
    """2 instancias: generador + reviewer."""
    return [
        build_role(RoleType.GENERATOR, "gen"),
        build_role(RoleType.REVIEWER, "review", max_steps=3),
    ]


def preset_dual_generator() -> List[SessionRole]:
    """2 instancias: generadores con diferentes enfoques."""
    return [
        build_role(RoleType.GENERATOR, "gen-A"),
        build_role(RoleType.GENERATOR, "gen-B"),
    ]


def preset_full_pipeline() -> List[SessionRole]:
    """3 instancias: generador + reviewer + tester."""
    return [
        build_role(RoleType.GENERATOR, "gen"),
        build_role(RoleType.REVIEWER, "review", max_steps=3),
        build_role(RoleType.TESTER, "test", max_steps=3),
    ]


def preset_specialist_pair(domain_a: str, domain_b: str) -> List[SessionRole]:
    """2 instancias: especialistas en dominios diferentes."""
    return [
        build_role(RoleType.SPECIALIST, f"spec-{domain_a}", domain=domain_a),
        build_role(RoleType.SPECIALIST, f"spec-{domain_b}", domain=domain_b),
    ]


def get_preset(name: str, **kwargs) -> List[SessionRole]:
    """Retorna un preset de roles por nombre.

    Args:
        name: Nombre del preset
        **kwargs: Argumentos adicionales (domain_a, domain_b para specialist)

    Returns:
        Lista de SessionRole
    """
    presets = {
        "generate-review": preset_generate_review,
        "dual-generator": preset_dual_generator,
        "full-pipeline": preset_full_pipeline,
    }

    if name == "specialist-pair":
        return preset_specialist_pair(
            kwargs.get("domain_a", "frontend"),
            kwargs.get("domain_b", "backend"),
        )

    factory = presets.get(name)
    if factory:
        return factory()

    # Default: generador + reviewer
    return preset_generate_review()
