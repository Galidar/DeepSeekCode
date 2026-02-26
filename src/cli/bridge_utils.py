"""Utilidades compartidas para modos programaticos de DeepSeek-Code.

Funciones de I/O, redireccion de output, carga de archivos y
creacion de la app. Usadas por oneshot.py y multi_step.py.
"""

import builtins
import json
import os
import sys

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR


def redirect_output():
    """Redirige stdout y builtins.print a stderr.

    En modo --json, tanto los prints internos como los console.print()
    de Rich contaminarian stdout. Este parche redirige TODO a stderr
    y luego restauramos stdout solo para escribir el JSON final.

    Returns:
        Tupla (original_print, original_stdout) para restaurar despues
    """
    original_print = builtins.print
    original_stdout = sys.stdout

    def patched_print(*args, **kwargs):
        kwargs.setdefault("file", sys.stderr)
        original_print(*args, **kwargs)

    builtins.print = patched_print
    sys.stdout = sys.stderr

    return original_print, original_stdout


def restore_output(original_print, original_stdout):
    """Restaura stdout y builtins.print originales."""
    builtins.print = original_print
    sys.stdout = original_stdout


def output_json(data: dict):
    """Escribe JSON al stdout de forma limpia."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def output_text(text: str):
    """Escribe texto plano al stdout."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def create_app(config):
    """Crea la app sin iniciar el modo interactivo."""
    from cli.main import DeepSeekCodeApp
    return DeepSeekCodeApp(config)


def load_file_safe(path: str, label: str = "Archivo") -> str:
    """Lee un archivo con validacion de existencia.

    Args:
        path: Ruta al archivo
        label: Nombre descriptivo para el error

    Returns:
        Contenido del archivo

    Raises:
        FileNotFoundError: Si el archivo no existe
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} no encontrado: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def check_credentials(config: dict) -> bool:
    """Verifica que hay credenciales configuradas.

    Returns:
        True si hay credenciales validas
    """
    bearer = config.get("bearer_token")
    cookies = config.get("cookies")
    return bool(bearer and cookies)


def handle_no_credentials(json_mode: bool, originals=None, mode: str = ""):
    """Maneja el caso de credenciales faltantes.

    Args:
        json_mode: Si True, emite JSON al stdout
        originals: Tupla de (print, stdout) para restaurar
        mode: Nombre del modo para el JSON
    """
    if json_mode:
        if originals:
            restore_output(*originals)
        error_data = {"success": False, "error": "No hay credenciales configuradas."}
        if mode:
            error_data["mode"] = mode
        output_json(error_data)
    else:
        print("Error: No hay credenciales. Ejecuta DeepSeek-Code primero.", file=sys.stderr)
    sys.exit(1)
