"""Tema visual profesional para DeepSeek-Code CLI.

Centraliza la estetica del terminal para lograr una apariencia
comparable a Claude Code: banner compacto, prompt limpio, respuestas
formateadas con Markdown y errores consistentes.
"""

import os
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from cli.config_loader import VERSION
from cli.i18n import t


def get_prompt_string(chat_name: str = None) -> str:
    """Retorna el string del prompt interactivo, opcionalmente con nombre de chat."""
    if chat_name:
        return f"[dim]{chat_name}[/dim] [bold cyan]>[/bold cyan]"
    return "[bold cyan]>[/bold cyan]"


def render_ascii_banner(console: Console):
    """Muestra solo el ASCII art DEEPSEEK CODE + version. Se llama SIEMPRE al inicio."""
    console.print()
    console.print("  [bold cyan]██████╗ ███████╗███████╗██████╗ ███████╗███████╗███████╗██╗  ██╗[/bold cyan]")
    console.print("  [bold cyan]██╔══██╗██╔════╝██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝██║ ██╔╝[/bold cyan]")
    console.print("  [bold cyan]██║  ██║█████╗  █████╗  ██████╔╝███████╗█████╗  █████╗  █████╔╝[/bold cyan]")
    console.print("  [bold cyan]██║  ██║██╔══╝  ██╔══╝  ██╔═══╝ ╚════██║██╔══╝  ██╔══╝  ██╔═██╗[/bold cyan]")
    console.print("  [bold cyan]██████╔╝███████╗███████╗██║     ███████║███████╗███████╗██║  ██╗[/bold cyan]")
    console.print("  [bold cyan]╚═════╝ ╚══════╝╚══════╝╚═╝     ╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝[/bold cyan]")
    console.print("        [bold white]██████╗ ██████╗ ██████╗ ███████╗[/bold white]")
    console.print("        [bold white]██╔════╝██╔═══██╗██╔══██╗██╔════╝[/bold white]")
    console.print("        [bold white]██║     ██║   ██║██║  ██║█████╗[/bold white]")
    console.print("        [bold white]██║     ██║   ██║██║  ██║██╔══╝[/bold white]")
    console.print("        [bold white]╚██████╗╚██████╔╝██████╔╝███████╗[/bold white]")
    console.print("        [bold white] ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝[/bold white]")
    console.print(f"  [dim]v{VERSION}[/dim]  [bold bright_magenta]by Galidar[/bold bright_magenta]")
    console.print()


def render_login_needed(console: Console):
    """Muestra mensaje de que necesita login — integrado en la misma experiencia."""
    console.print(f"  [yellow]{t('login_needed')}[/yellow]")
    console.print()


def render_welcome_banner(console: Console, mode_label: str, ctx_label: str,
                          tools_count: int, access_label: str,
                          summary_threshold: int, max_summaries: int,
                          appdata_dir: str, skills_dir: str,
                          config: dict):
    """Muestra tablas de estado y comandos (sin ASCII art, que ya se mostro antes)."""
    # Tabla de estado compacta
    table = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
        expand=False
    )
    table.add_column("key", style="dim", no_wrap=True)
    table.add_column("value", style="bold")

    table.add_row(t("mode"), mode_label)
    table.add_row(t("context"), ctx_label)
    table.add_row(t("tools"), str(tools_count))
    table.add_row(t("access"), access_label)

    serena_project = config.get("serena_project")
    if serena_project:
        table.add_row("Serena", os.path.basename(serena_project))

    console.print(table)
    console.print()

    # Tabla de comandos disponibles
    cmd_table = Table(
        show_header=False,
        box=None,
        padding=(0, 1),
        expand=False
    )
    cmd_table.add_column("cmd", style="cyan", no_wrap=True)
    cmd_table.add_column("desc", style="dim")

    cmd_table.add_row("  /agent <meta>", t("cmd_agent"))
    cmd_table.add_row("  /skill <nombre>", t("cmd_skill"))
    cmd_table.add_row("  /skills", t("cmd_skills"))
    cmd_table.add_row("  /new [nombre]", "New chat")
    cmd_table.add_row("  /chats", "List chats")
    cmd_table.add_row("  /switch <nombre>", "Switch chat")
    cmd_table.add_row("  /close [nombre]", "Close chat")
    cmd_table.add_row("  /chat", "Current chat info")
    cmd_table.add_row("  /serena", t("cmd_serena"))
    cmd_table.add_row("  /login", t("cmd_login"))
    cmd_table.add_row("  /logout", t("cmd_logout"))
    cmd_table.add_row("  /health", t("cmd_health"))
    cmd_table.add_row("  /account", t("cmd_account"))
    cmd_table.add_row("  /keys", t("cmd_keys"))
    cmd_table.add_row("  /test", t("cmd_test"))
    cmd_table.add_row("  /lang", t("cmd_lang"))
    cmd_table.add_row("  /exit", t("cmd_exit"))

    console.print(f"  [bold]{t('commands_available')}[/bold]")
    console.print(cmd_table)
    console.print()


def render_response(console: Console, response: str):
    """Renderiza una respuesta del modelo con Markdown limpio."""
    console.print()
    console.print(Panel(
        Markdown(response),
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2)
    ))
    console.print()


def render_error(console: Console, message: str):
    """Renderiza un mensaje de error con formato consistente."""
    console.print(f"\n  [bold red]Error:[/bold red] {message}\n")


def render_status(console: Console, message: str):
    """Renderiza un mensaje de estado/info."""
    console.print(f"  [cyan]{message}[/cyan]")


def render_warning(console: Console, message: str):
    """Renderiza un mensaje de advertencia."""
    console.print(f"  [yellow]{message}[/yellow]")


def render_success(console: Console, message: str):
    """Renderiza un mensaje de exito."""
    console.print(f"  [bold green]{message}[/bold green]")
