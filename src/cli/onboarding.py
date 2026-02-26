"""Onboarding para usuarios nuevos de DeepSeek-Code.

Flujo integrado que se ejecuta dentro de la misma experiencia visual
del banner principal (estilo Claude Code). El ASCII art ya se mostro
en main.py antes de llegar aqui.
"""

import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from cli.config_loader import APPDATA_DIR
from cli.ui_theme import render_login_needed
from cli.i18n import t, set_language, get_language, LANGUAGES

console = Console()


def needs_onboarding(config: dict) -> bool:
    """Determina si el usuario necesita onboarding (no tiene credenciales web)."""
    bearer_token = config.get("bearer_token")
    cookies = config.get("cookies")
    return not (bearer_token and cookies)


def needs_language_selection(config: dict) -> bool:
    """Determina si necesita selector de idioma (primera vez)."""
    return config.get("lang") is None


def ask_language(config: dict) -> dict:
    """Selector de idioma. Guarda en config y aplica."""
    console.print(f"  [bold]{t('lang_select')}[/bold]\n")
    for i, (code, name) in enumerate(LANGUAGES.items(), 1):
        console.print(f"  [cyan][{i}][/cyan] {name}")
    console.print()

    choice = Prompt.ask("  >", choices=["1", "2", "3"], default="1")
    lang_codes = list(LANGUAGES.keys())
    lang = lang_codes[int(choice) - 1]

    set_language(lang)
    config["lang"] = lang
    _save_config(config)
    return config


async def run_onboarding(config: dict):
    """Flujo de login web integrado (el banner ya se mostro en main.py).

    Va directo al login web — no hay seleccion de modo.
    Retorna el config actualizado con credenciales, o None si cancelado.
    """
    render_login_needed(console)
    return await _setup_web_login(config)


def _show_progress(step: int, total: int, label: str, status: str = ""):
    """Muestra progreso visual paso a paso."""
    filled = step
    empty = total - step
    bar = "[green]" + ("█" * filled) + "[/green][dim]" + ("░" * empty) + "[/dim]"
    suffix = f"  [green]{status}[/green]" if status else ""
    console.print(f"  {bar} {t('step_label', step=step, total=total, label=label)}{suffix}")


async def _setup_web_login(config: dict):
    """Flujo de configuracion con cuenta web (gratis) y progreso visual."""
    console.print()
    console.print(f"  [bold]{t('web_config')}[/bold]")
    console.print()

    # Paso 1: Verificar PyQt5
    _show_progress(1, 4, t("checking_deps"))
    from deepseek_code.auth.web_login import PYQT_AVAILABLE
    if not PYQT_AVAILABLE:
        console.print(f"[red]  {t('pyqt_missing')}[/red]")
        console.print(f"  {t('pyqt_install')}")
        return None
    _show_progress(1, 4, t("checking_deps"), t("pyqt_available"))

    # Paso 2: Asegurar WASM
    _show_progress(2, 4, t("preparing_components"))
    wasm_path = _ensure_wasm(config)
    if not wasm_path:
        console.print(f"[red]  {t('wasm_failed')}[/red]")
        console.print(f"  {t('check_internet')}")
        return None
    _show_progress(2, 4, t("preparing_components"), t("wasm_ready"))

    # Paso 3: Login
    _show_progress(3, 4, t("opening_login"))
    console.print()
    console.print(Panel(
        f"  {t('instr_1')}\n"
        f"  {t('instr_2')}\n"
        f"  {t('instr_3')}\n\n"
        f"  [dim]{t('instr_tip')}[/dim]",
        title=f"[bold cyan]{t('instructions_title')}[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1)
    ))

    from deepseek_code.auth.web_login import run_login
    config_path = config.get("_config_path", os.path.join(APPDATA_DIR, 'config.json'))
    result = run_login(config_path, wasm_path=wasm_path)

    # Paso 4: Validar resultado
    if result.get("validated"):
        _show_progress(4, 4, t("validating_session"), t("pow_valid"))
        console.print()
        console.print(f"  [bold green]{t('session_configured')}[/bold green]")

        from cli.config_loader import load_config
        config = load_config()

        _auto_save_account(config, "default-web")

        console.print()
        return config
    elif result.get("bearer_token"):
        _show_progress(4, 4, t("validating_session"), t("pow_failed"))
        console.print(f"  [yellow]{t('creds_captured_but', error=result.get('error'))}[/yellow]")
        from cli.config_loader import load_config
        config = load_config()
        return config
    elif result.get("cookies"):
        console.print(f"  [yellow]{t('only_cookies')}[/yellow]")
        retry = Confirm.ask(f"  {t('retry_question')}", default=True)
        if retry:
            return await _setup_web_login(config)
        return None
    else:
        console.print(f"  [red]{t('no_creds')}[/red]")
        retry = Confirm.ask(f"  {t('retry_question')}", default=True)
        if retry:
            return await _setup_web_login(config)
        return None


def _auto_save_account(config: dict, default_name: str):
    """Auto-guarda la config actual como cuenta nombrada."""
    try:
        from deepseek_code.auth.account_manager import AccountManager
        am = AccountManager(APPDATA_DIR)
        name = Prompt.ask(f"  {t('account_name_prompt')}", default=default_name)
        am.add_account(name, config)
        console.print(f"  [dim]{t('account_saved', name=name)}[/dim]")
    except Exception:
        pass


def _ensure_wasm(config: dict) -> str:
    """Asegura que el WASM este disponible. Descarga si no existe."""
    from deepseek_code.auth.web_login import _find_wasm, _download_wasm

    config_path = config.get("_config_path", os.path.join(APPDATA_DIR, 'config.json'))

    existing = _find_wasm(config_path)
    if existing:
        return existing

    dest = os.path.join(APPDATA_DIR, "sha3_wasm_bg.wasm")
    console.print(f"  [cyan]{t('downloading_wasm')}[/cyan]")
    if _download_wasm(dest):
        return dest
    return None


def _save_config(config: dict):
    """Guarda config con DPAPI."""
    from cli.secure_config import save_config_secure
    config_path = config.get("_config_path", os.path.join(APPDATA_DIR, 'config.json'))
    save_config_secure(config, config_path)
