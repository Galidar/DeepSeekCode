"""Helpers para comandos CLI — funciones extraidas para mantener commands.py < 400 LOC."""

import os

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich import box

from cli.i18n import t

console = Console()


async def run_knowledge_skill(client, skill, query: str = None):
    """Ejecuta un skill de conocimiento: inyecta el contenido como contexto."""
    desc_preview = skill.description[:100] + "..." if len(skill.description) > 100 else skill.description
    console.print(Panel.fit(
        f"[bold]{skill.name}[/bold] — {desc_preview}\n"
        f"[dim]Knowledge: {len(skill.content)} chars[/dim]",
        title="[bold magenta]Knowledge Skill[/bold magenta]",
        border_style="magenta"
    ))

    if not query:
        console.print(f"[yellow]{t('knowledge_skill_hint')}[/yellow]")
        console.print(f"  /skill {skill.name} <your question>")
        return

    context_msg = (
        f"You have access to the following documentation from skill '{skill.name}':\n\n"
        f"---\n{skill.content}\n---\n\n"
        f"Based ONLY on the documentation above, answer: {query}"
    )

    console.print(f"  [cyan]{t('knowledge_consulting', name=skill.name)}[/cyan]")
    try:
        with console.status(f"[bold green]{t('thinking')}"):
            response = await client.chat(context_msg)
        console.print(Panel(
            Markdown(response),
            title=f"[bold green]{skill.name}[/bold green]",
            border_style="green",
            box=box.ROUNDED
        ))
    except Exception as e:
        console.print(f"[red]{t('knowledge_error', error=str(e))}[/red]")


async def handle_web_login(config: dict, appdata_dir: str, session_manager=None):
    """Ejecuta web_login con hot-reload (sin necesidad de reiniciar)."""
    from deepseek_code.auth.web_login import run_login, PYQT_AVAILABLE
    if not PYQT_AVAILABLE:
        console.print(f"[red]{t('login_pyqt_missing')}[/red]")
        return
    wasm_path = config.get("wasm_path", "")
    config_path = config.get("_config_path", os.path.join(appdata_dir, 'config.json'))
    console.print(f"[cyan]{t('login_opening')}[/cyan]")
    result = run_login(config_path, wasm_path=wasm_path)
    if result.get("validated"):
        console.print(f"[bold green]{t('login_validated')}[/bold green]")
        if session_manager:
            from cli.config_loader import load_config
            new_config = load_config()
            session_manager.hot_reload(new_config)
            console.print(f"[green]{t('login_renewed')}[/green]")
        else:
            console.print(f"[yellow]{t('login_restart')}[/yellow]")
    elif result.get("bearer_token"):
        console.print(f"[yellow]{t('login_creds_but', error=result.get('error'))}[/yellow]")
    elif result.get("cookies"):
        console.print(f"[yellow]{t('login_only_cookies')}[/yellow]")
    else:
        console.print(f"[red]{t('login_no_creds')}[/red]")


async def handle_web_test(config: dict):
    """Ejecuta web_test directamente sin pasar por DeepSeek."""
    from deepseek_code.auth.web_login import validate_session
    from cli.config_loader import load_config
    config = load_config()
    bearer_token = config.get("bearer_token")
    cookies = config.get("cookies")
    if not bearer_token or not cookies:
        console.print(f"[red]{t('test_missing')}[/red]")
        return
    wasm_path = config.get("wasm_path", "")
    console.print(f"[cyan]{t('test_validating')}[/cyan]")
    if validate_session(bearer_token, cookies, wasm_path):
        console.print(f"[bold green]{t('test_valid')}[/bold green]")
    else:
        console.print(f"[red]{t('test_invalid')}[/red]")


async def handle_health(session_manager):
    """Health check manual de la sesion."""
    if not session_manager:
        console.print(f"[yellow]{t('health_unavailable')}[/yellow]")
        return

    console.print(f"[cyan]{t('health_running')}[/cyan]")
    result = await session_manager.health_check()
    status = session_manager.get_status()

    mode_label = {
        "web": t("health_mode_web"),
        "api": t("health_mode_api"),
        "none": t("health_mode_none"),
    }.get(status["mode"], status["mode"])

    valid_icon = f"[green]{t('health_ok')}[/green]" if status["valid"] else f"[red]{t('health_fail')}[/red]"
    if status["valid"] is None:
        valid_icon = f"[yellow]{t('health_not_checked')}[/yellow]"

    last_check = status.get("last_check_seconds_ago")
    last_str = t("health_last_check", time=last_check) if last_check else t("health_last_never")

    lines = [
        f"  {t('mode')}: {mode_label}",
        f"  Status: {valid_icon}",
        f"  {last_str}",
        f"  {t('health_failures', n=status['consecutive_failures'])}",
        f"  Bearer: {t('yes') if status['has_bearer'] else t('no')}",
        f"  Cookies: {t('yes') if status['has_cookies'] else t('no')}",
        f"  API key: {t('yes') if status['has_api_key'] else t('no')}",
    ]
    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Health Check[/bold cyan]",
        border_style="cyan"
    ))


async def handle_account(appdata_dir: str, args: str, session_manager=None):
    """Gestion de multiples cuentas."""
    from deepseek_code.auth.account_manager import AccountManager

    am = AccountManager(appdata_dir)
    parts = args.split(maxsplit=1) if args else []
    subcmd = parts[0].lower() if parts else "list"
    extra = parts[1].strip() if len(parts) > 1 else ""

    if subcmd == "list" or subcmd == "":
        accounts = am.list_accounts()
        active = am.get_active_account()
        if not accounts:
            console.print(f"[yellow]{t('account_none')}[/yellow]")
            console.print(t("account_use_add"))
            return
        console.print(f"  [bold]{t('account_active', name=active or 'none')}[/bold]\n")
        for acc in accounts:
            marker = "[green]*[/green] " if acc["is_active"] else "  "
            console.print(f"  {marker}{acc['name']} [{acc['mode']}]")

    elif subcmd == "switch":
        if not extra:
            console.print(f"[red]{t('account_switch_usage')}[/red]")
            return
        creds = am.switch_account(extra)
        if creds is None:
            console.print(f"[red]{t('account_not_found', name=extra)}[/red]")
            return
        if session_manager:
            from cli.config_loader import load_config
            from cli.secure_config import save_config_secure
            config_path = os.path.join(appdata_dir, 'config.json')
            current = load_config()
            for field in ("bearer_token", "cookies", "api_key", "wasm_path"):
                current[field] = creds.get(field, current.get(field))
            save_config_secure(current, config_path)
            session_manager.hot_reload(current)
        console.print(f"[green]{t('account_switched', name=extra, mode=creds.get('mode', '?'))}[/green]")

    elif subcmd == "add":
        from cli.config_loader import load_config
        from rich.prompt import Prompt
        config = load_config()
        name = extra or Prompt.ask(f"  {t('account_name_prompt')}", default=t("account_name_default"))
        am.add_account(name, config)
        console.print(f"[green]{t('account_added', name=name)}[/green]")

    elif subcmd == "remove":
        if not extra:
            console.print(f"[red]{t('account_remove_usage')}[/red]")
            return
        removed = am.remove_account(extra)
        if removed:
            console.print(f"[green]{t('account_removed', name=extra)}[/green]")
        else:
            console.print(f"[red]{t('account_not_found', name=extra)}[/red]")

    else:
        console.print(Panel(
            Markdown(
                "**Account:**\n\n"
                "- `/account` or `/account list` - List accounts\n"
                "- `/account switch <name>` - Switch account\n"
                "- `/account add [name]` - Save current account\n"
                "- `/account remove <name>` - Remove account\n"
            ),
            title="[bold cyan]Account[/bold cyan]",
            border_style="cyan"
        ))


async def handle_logout(config: dict, appdata_dir: str, session_manager=None):
    """Cierra la sesion actual limpiando credenciales del config.

    Permite al usuario cambiar de cuenta sin reiniciar la app.
    Ofrece re-login inmediato despues de limpiar.
    """
    from rich.prompt import Confirm
    from cli.config_loader import load_config
    from cli.secure_config import save_config_secure

    bearer = config.get("bearer_token")
    api_key = config.get("api_key")

    if not bearer and not api_key:
        console.print(f"[yellow]{t('logout_no_session')}[/yellow]")
        return

    # Mostrar que cuenta esta activa
    mode = t("health_mode_web") if bearer else t("health_mode_api")
    console.print(f"\n  {t('logout_current', mode=mode)}")

    # Confirmar
    confirmed = Confirm.ask(f"  {t('logout_confirm')}", default=False)
    if not confirmed:
        console.print(f"  [dim]{t('logout_cancelled')}[/dim]")
        return

    # Limpiar credenciales del config
    config["bearer_token"] = None
    config["cookies"] = None
    config["api_key"] = None

    config_path = config.get("_config_path", os.path.join(appdata_dir, 'config.json'))
    save_config_secure(config, config_path)

    # Resetear session manager
    if session_manager:
        session_manager.hot_reload(config)

    console.print(f"  [green]{t('logout_done')}[/green]")

    # Ofrecer re-login
    relogin = Confirm.ask(f"  {t('logout_relogin')}", default=True)
    if relogin:
        await handle_web_login(config, appdata_dir, session_manager)
