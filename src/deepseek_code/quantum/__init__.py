"""QuantumBridge: Sistema de delegacion paralela dual para DeepSeek-Code."""

from .dual_session import DualSession
from .angle_detector import detect_angles, AngleSpec, build_angle_system_prompt
from .merge_engine import merge_responses, MergeResult
from .merge_helpers import extract_todo_blocks, extract_functions, validate_braces
