"""Handlers para comandos /agent, /skill, /skills, /serena del CLI.

Funciones grandes (login, health, account, knowledge_skill) estan en
commands_helpers.py para mantener este archivo < 400 LOC.
"""

import os
import signal

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich import box

from cli.i18n import t
from cli.commands_helpers import (
    run_knowledge_skill,
    handle_web_login,
    handle_web_test,
    handle_health,
    handle_account,
)

console = Console()


async def handle_serena(serena_manager, mcp_server, client, config, args: str):
    """Maneja el comando /serena con subcomandos start/stop/restart/status."""
    from deepseek_code.serena.manager import SerenaManager

    parts = args.split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"
    extra = parts[1] if len(parts) > 1 else None

    if subcmd == "start":
        if serena_manager is None:
            serena_manager = SerenaManager(
                mcp_server=mcp_server,
                deepseek_client=client,
                command=config.get("serena_command", "serena-agent"),
                prefix=config.get("serena_prefix", "serena_")
            )
        with console.status(f"[cyan]{t('starting_serena')}[/cyan]"):
            success, msg = await serena_manager.start(project_override=extra)
        color = "green" if success else "red"
        console.print(f"[{color}]{msg}[/{color}]")
        return serena_manager

    elif subcmd == "stop":
        if not serena_manager:
            console.print(f"[yellow]{t('serena_not_init')}[/yellow]")
            return serena_manager
        msg = await serena_manager.stop()
        console.print(f"[green]{msg}[/green]")
        return serena_manager

    elif subcmd == "restart":
        if not serena_manager:
            console.print(f"[yellow]{t('serena_use_start')}[/yellow]")
            return serena_manager
        with console.status(f"[cyan]{t('restarting_serena')}[/cyan]"):
            success, msg = await serena_manager.restart(project_override=extra)
        color = "green" if success else "red"
        console.print(f"[{color}]{msg}[/{color}]")
        return serena_manager

    elif subcmd == "status":
        if not serena_manager:
            console.print(f"[yellow]{t('serena_use_start')}[/yellow]")
            return serena_manager
        info = serena_manager.status()
        status_str = f"[green]{t('serena_status_active')}[/green]" if info["running"] else f"[red]{t('serena_status_stopped')}[/red]"
        console.print(f"Serena: {status_str}")
        console.print(t("serena_tools", count=info['tools_count']))
        if info["project"]:
            console.print(t("serena_project", path=info['project']))
        if info["tools"]:
            console.print(f"Tools: {', '.join(info['tools'][:10])}")
        return serena_manager

    else:
        console.print(Panel(
            Markdown(
                "**Serena:**\n\n"
                "- `/serena start [path]` - Start Serena\n"
                "- `/serena stop` - Stop Serena\n"
                "- `/serena restart [path]` - Restart Serena\n"
                "- `/serena status` - View status\n"
            ),
            title="[bold cyan]Serena[/bold cyan]",
            border_style="cyan"
        ))
        return serena_manager


async def run_agent(client, config, mcp_server, appdata_dir: str, goal: str):
    """Ejecuta el agente autonomo con una meta (funciona en API y web)."""
    from deepseek_code.agent.engine import AgentEngine

    console.print(Panel.fit(
        f"[bold]{t('agent_meta', goal=goal)}[/bold]",
        title=f"[bold cyan]{t('agent_panel_title')}[/bold cyan]",
        border_style="cyan"
    ))

    def on_step(step):
        preview = step.response[:2000] + "..." if len(step.response) > 2000 else step.response
        console.print(f"  [cyan]{t('agent_step', n=step.step_number, preview=preview)}[/cyan]")

    def on_status(status):
        console.print(f"  [yellow][{status.value}][/yellow]")

    agent = AgentEngine(
        client=client,
        max_steps=config.get("agent_max_steps", 50),
        logs_dir=os.path.join(appdata_dir, "agent_logs"),
        on_step=on_step,
        on_status=on_status
    )

    interrupted = False
    original_handler = signal.getsignal(signal.SIGINT)

    def handler(sig, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            console.print(f"\n[yellow]{t('agent_interrupt')}[/yellow]")
            agent.interrupt()

    signal.signal(signal.SIGINT, handler)
    try:
        result = await agent.run(goal)
        status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
        is_ok = status_str == "completado"
        console.print(Panel(
            Markdown(result.final_summary or t("agent_no_summary")),
            title=f"[bold {'green' if is_ok else 'yellow'}]{t('agent_result', status=status_str)}[/bold {'green' if is_ok else 'yellow'}]",
            subtitle=t("agent_stats", steps=len(result.steps), time=result.total_duration_s),
            border_style="green" if is_ok else "yellow"
        ))
        if result.log_file:
            console.print(f"[dim]{t('agent_log', path=result.log_file)}[/dim]")
    except Exception as e:
        console.print(f"[red]{t('agent_error', error=str(e))}[/red]")
    finally:
        signal.signal(signal.SIGINT, original_handler)


async def run_skill(client, mcp_server, config, appdata_dir: str, args_str: str):
    """Ejecuta un skill por nombre con argumentos."""
    from deepseek_code.skills.loader import SkillLoader, KnowledgeSkill
    from deepseek_code.skills.runner import SkillRunner

    parts = args_str.split(maxsplit=1)
    if not parts:
        console.print(f"[red]{t('skill_usage')}[/red]")
        return

    skill_name = parts[0]
    skills_dir = config.get("skills_dir", os.path.join(appdata_dir, "skills"))
    loader = SkillLoader(skills_dir)
    skill = loader.load_one(skill_name)

    if not skill:
        console.print(f"[red]{t('skill_not_found', name=skill_name, dir=skills_dir)}[/red]")
        return

    if isinstance(skill, KnowledgeSkill):
        await run_knowledge_skill(client, skill, parts[1].strip() if len(parts) > 1 else None)
        return

    params = {}
    if len(parts) > 1:
        raw_args = parts[1].strip()
        if "=" in raw_args:
            for pair in raw_args.split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v
        else:
            for p in skill.parameters:
                if p.required and p.name not in params:
                    params[p.name] = raw_args
                    break

    console.print(Panel.fit(
        f"[bold]{skill.name}[/bold] — {skill.description}",
        title="[bold cyan]Skill[/bold cyan]",
        border_style="cyan"
    ))

    def on_step(step, result):
        status = f"[green]{t('skill_ok')}[/green]" if result.get("success") else f"[red]{t('skill_fail')}[/red]"
        console.print(f"  {status} {step.description or step.id}")

    runner = SkillRunner(mcp_server, on_step=on_step)
    try:
        results = await runner.run(skill, params)
        output = runner.resolve_output(skill, params, results)
        console.print(Panel(output, title="[bold green]Result[/bold green]", border_style="green"))
    except Exception as e:
        console.print(f"[red]{t('skill_error', error=str(e))}[/red]")


def handle_keys_help():
    """Muestra ayuda de comandos."""
    help_text = (
        "**Commands:**\n\n"
        "- `/agent <goal>` - Autonomous agent\n"
        "- `/skill <name>` - Run skill\n"
        "- `/skills` - List skills\n"
        "- `/login` - Web login (hot reload)\n"
        "- `/test` - Validate session\n"
        "- `/health` - Session health check\n"
        "- `/account` - Account management\n"
        "- `/serena` - Serena control\n"
        "- `/lang` - Change language\n"
        "- `/keys` - This help\n"
        "- `/exit` - Exit\n\n"
        "**API key:** Edit `config.json` in AppData -> `\"api_key\": \"sk-...\"`"
    )
    console.print(Panel(Markdown(help_text), title="[bold cyan]Help[/bold cyan]", border_style="cyan"))


async def list_skills(config, appdata_dir: str):
    """Lista todos los skills disponibles."""
    from deepseek_code.skills.loader import SkillLoader, KnowledgeSkill

    skills_dir = config.get("skills_dir", os.path.join(appdata_dir, "skills"))
    loader = SkillLoader(skills_dir)
    skills = loader.load_all()

    if not skills:
        console.print(f"[yellow]{t('no_skills', dir=skills_dir)}[/yellow]")
        console.print(t("add_skills_hint"))
        return

    lines = []
    for name, skill in skills.items():
        if isinstance(skill, KnowledgeSkill):
            size_kb = len(skill.content) / 1024
            lines.append(f"**{name}** [{t('knowledge_tag', size=f'{size_kb:.0f}')}] — {skill.description[:300]}...")
        else:
            param_names = ", ".join(p.name for p in skill.parameters)
            lines.append(f"**{name}** [{t('workflow_tag')}] ({param_names}) — {skill.description}")

    console.print(Panel(
        Markdown("\n".join(lines)),
        title=f"[bold cyan]{t('skills_panel', count=len(skills))}[/bold cyan]",
        border_style="cyan"
    ))
