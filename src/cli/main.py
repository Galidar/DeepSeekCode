#!/usr/bin/env python3
"""CLI principal para DeepSeek-Code con soporte para API key y sesion web."""

import asyncio
import argparse
import os
import sys

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False
    import select

from rich.console import Console
from rich.prompt import Prompt

from cli.config_loader import load_config, APPDATA_DIR, SKILLS_DIR
from cli.i18n import t, set_language, get_language, LANGUAGES

from deepseek_code.server.protocol import MCPServer
from deepseek_code.tools.filesystem import (
    ReadFileTool, WriteFileTool, ListDirectoryTool,
    DeleteFileTool, MoveFileTool, CopyFileTool
)
from deepseek_code.tools.file_editor import EditFileTool
from deepseek_code.tools.shell import RunCommandTool
from deepseek_code.tools.memory_tool import MemoryTool
from deepseek_code.tools.key_manager import ManageKeysTool
from deepseek_code.tools.archive_tool import ArchiveTool
from deepseek_code.tools.file_utils import FindFilesTool, FileInfoTool, MakeDirectoryTool
from deepseek_code.client.deepseek_client import DeepSeekCodeClient
from deepseek_code.security.sandbox import RateLimiter
from deepseek_code.serena.manager import SerenaManager
from deepseek_code.auth.session_manager import SessionManager
from deepseek_code.auth.token_monitor import TokenMonitor
from cli.commands import run_agent, run_skill, list_skills, handle_serena, handle_keys_help
from cli.commands_helpers import handle_web_login, handle_web_test, handle_health, handle_account, handle_logout

console = Console()


def _drain_stdin_buffer() -> str:
    """Drena lineas adicionales del buffer de stdin (texto pegado multilinea).

    En Windows usa msvcrt.kbhit(), en Unix usa select().
    Retorna las lineas extra concatenadas, o cadena vacia si no hay nada.
    """
    extra_lines = []
    try:
        if _HAS_MSVCRT:
            while msvcrt.kbhit():
                line = sys.stdin.readline()
                if not line:
                    break
                extra_lines.append(line.rstrip('\n').rstrip('\r'))
        else:
            while select.select([sys.stdin], [], [], 0.05)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                extra_lines.append(line.rstrip('\n').rstrip('\r'))
    except Exception:
        pass
    return '\n'.join(extra_lines)


def read_multiline_input(prompt_str: str) -> str:
    """Lee input del usuario con soporte para texto pegado multilinea.

    1. Muestra el prompt y lee la primera linea con Prompt.ask()
    2. Drena cualquier linea adicional en el buffer de stdin (texto pegado)
    3. Retorna todo el texto unido
    """
    first_line = Prompt.ask(prompt_str)
    extra = _drain_stdin_buffer()
    if extra:
        return first_line + '\n' + extra
    return first_line


class DeepSeekCodeApp:
    def __init__(self, config: dict):
        self.config = config
        self.mcp_server = MCPServer(name="deepseek-code-local")

        allowed_paths = config.get("allowed_paths", [])
        self.mcp_server.register_tool(ReadFileTool(allowed_paths))
        self.mcp_server.register_tool(WriteFileTool(allowed_paths))
        self.mcp_server.register_tool(ListDirectoryTool(allowed_paths))
        self.mcp_server.register_tool(DeleteFileTool(allowed_paths))
        self.mcp_server.register_tool(MoveFileTool(allowed_paths))
        self.mcp_server.register_tool(CopyFileTool(allowed_paths))
        self.mcp_server.register_tool(EditFileTool(allowed_paths))
        self.mcp_server.register_tool(ArchiveTool(allowed_paths))
        self.mcp_server.register_tool(FindFilesTool(allowed_paths))
        self.mcp_server.register_tool(FileInfoTool(allowed_paths))
        self.mcp_server.register_tool(MakeDirectoryTool(allowed_paths))

        allowed_commands = config.get("allowed_commands", [])
        self.mcp_server.register_tool(RunCommandTool(allowed_commands, allowed_paths=allowed_paths))

        memory_path = config.get("memory_path", os.path.join(APPDATA_DIR, 'memory.md'))
        self.mcp_server.register_tool(MemoryTool(memory_path))

        from deepseek_code.tools.git_conflict_tool import ResolveConflictsTool
        self.mcp_server.register_tool(ResolveConflictsTool(allowed_paths))

        # Session manager para auto-recovery y health check
        self.session_manager = SessionManager(config, APPDATA_DIR)

        self.client = self._create_client(config)
        self.mcp_server.register_tool(ManageKeysTool(
            config_path=config.get("_config_path", os.path.join(APPDATA_DIR, 'config.json')),
            deepseek_client=self.client
        ))

        self.rate_limiter = RateLimiter(max_calls=200, per_seconds=60)
        self.token_monitor = TokenMonitor(self.session_manager)

        self.serena_manager = None
        if config.get("serena_enabled", True):
            self.serena_manager = SerenaManager(
                mcp_server=self.mcp_server, deepseek_client=self.client,
                command=config.get("serena_command", "serena-agent"),
                project=config.get("serena_project"),
                prefix=config.get("serena_prefix", "serena_"),
                allowed_paths=allowed_paths,
            )

    def _create_client(self, config):
        """Crea el cliente DeepSeek en modo web (unico modo soportado)."""
        bearer_token = config.get("bearer_token")
        cookies = config.get("cookies")
        wasm_path = config.get("wasm_path", os.path.join(APPDATA_DIR, "sha3_wasm_bg.wasm"))

        if not (bearer_token and cookies):
            raise ValueError(t("no_credentials"))

        if not os.path.exists(wasm_path):
            console.print(f"[cyan]{t('downloading_wasm_needed')}[/cyan]")
            from deepseek_code.auth.web_login import _download_wasm
            if not _download_wasm(wasm_path):
                raise FileNotFoundError(t("wasm_failed"))
            console.print(f"[green]{t('wasm_downloaded')}[/green]")

        console.print(f"[green]{t('mode_web_active')}[/green]")
        return DeepSeekCodeClient(
            bearer_token=bearer_token, cookies=cookies, wasm_path=wasm_path,
            mcp_server=self.mcp_server, memory_path=config.get("memory_path"),
            summary_threshold=config.get("summary_threshold", 80),
            skills_dir=config.get("skills_dir", SKILLS_DIR),
            session_manager=self.session_manager,
        )

    async def run_interactive(self):
        """Modo interactivo"""
        from cli.ui_theme import render_welcome_banner, render_response, render_error, get_prompt_string

        tools_list = [t_name for t_name in self.mcp_server.tools.keys()]
        mode_label = t("mode_web_label") if self.client.mode == "web" else t("mode_api_label")
        ctx_tokens = self.client.max_context_tokens
        ctx_label = f"{ctx_tokens // 1000}K" if ctx_tokens < 1_000_000 else f"{ctx_tokens // 1_000_000}M"
        has_path_restrictions = len(self.config.get("allowed_paths", [])) > 0
        access_label = t("access_restricted") if has_path_restrictions else t("access_full")

        render_welcome_banner(console, mode_label, ctx_label, len(tools_list),
                              access_label, self.client.summary_threshold,
                              self.client.max_summaries, APPDATA_DIR, SKILLS_DIR,
                              self.config)

        # Gestion de chats: cada chat es una sesion persistente independiente
        from cli.chat_manager import ChatManager
        self.chat_mgr = ChatManager(self.client)
        self.chat_mgr.init_or_resume()
        console.print(f"  [dim]Chat:[/dim] [bold cyan]{self.chat_mgr.current}[/bold cyan]")

        if self.serena_manager:
            console.print(f"[cyan]{t('starting_serena')}[/cyan]")
            success, msg = await self.serena_manager.start()
            console.print(f"[green]{msg}[/green]" if success else f"[yellow]Serena: {msg}[/yellow]")

        await self.token_monitor.start()

        while True:
            user_input = read_multiline_input(get_prompt_string(self.chat_mgr.current))
            if user_input.lower() == '/exit':
                await self.token_monitor.stop()
                console.print(f"[yellow]{t('goodbye')}[/yellow]")
                break

            cmd = user_input.lower().strip()
            if cmd == '/skills':
                await list_skills(self.config, APPDATA_DIR)
                continue
            if cmd.startswith('/agent'):
                args = user_input[6:].strip()
                if args:
                    await run_agent(self.client, self.config, self.mcp_server, APPDATA_DIR, args)
                else:
                    console.print(f"[yellow]{t('usage_agent')}[/yellow]")
                continue
            if cmd.startswith('/skill'):
                args = user_input[6:].strip()
                if args:
                    await run_skill(self.client, self.mcp_server, self.config, APPDATA_DIR, args)
                else:
                    console.print(f"[yellow]{t('usage_skill')}[/yellow]")
                continue
            if cmd.startswith('/serena'):
                args = user_input[7:].strip()
                self.serena_manager = await handle_serena(
                    self.serena_manager, self.mcp_server, self.client, self.config, args
                )
                continue
            if cmd.startswith('/logout'):
                await handle_logout(self.config, APPDATA_DIR, self.session_manager)
                continue
            if cmd.startswith('/login'):
                await handle_web_login(self.config, APPDATA_DIR, self.session_manager)
                continue
            if cmd.startswith('/test'):
                await handle_web_test(self.config)
                continue
            if cmd.startswith('/health'):
                await handle_health(self.session_manager)
                continue
            if cmd.startswith('/account'):
                args = user_input[8:].strip()
                await handle_account(APPDATA_DIR, args, self.session_manager)
                continue
            if cmd.startswith('/keys'):
                handle_keys_help()
                continue
            if cmd.startswith('/lang'):
                _handle_lang_command(self.config)
                continue

            # --- Comandos de gestion de chats ---
            if cmd == '/chat':
                info = self.chat_mgr.info()
                console.print(f"  [dim]Chat actual:[/dim] [bold cyan]{info['name']}[/bold cyan]  (mensajes: {info['messages']})")
                continue
            if cmd == '/chats':
                chats = self.chat_mgr.list_all()
                if not chats:
                    console.print("  [dim]No hay chats activos.[/dim]")
                else:
                    for c in chats:
                        marker = " [green]*[/green]" if c["current"] else ""
                        console.print(f"  [cyan]{c['name']:<20}[/cyan] msgs: {c['messages']:<3}{marker}")
                continue
            if cmd.startswith('/new'):
                name = user_input[4:].strip() or None
                self.chat_mgr.new_chat(name)
                console.print(f"  [green]Nuevo chat:[/green] [bold cyan]{self.chat_mgr.current}[/bold cyan]")
                continue
            if cmd.startswith('/switch'):
                name = user_input[7:].strip()
                if not name:
                    console.print("  [yellow]Uso: /switch <nombre>[/yellow]")
                elif self.chat_mgr.switch(name):
                    console.print(f"  [green]Cambiado a:[/green] [bold cyan]{self.chat_mgr.current}[/bold cyan]")
                else:
                    console.print(f"  [red]Chat '{name}' no encontrado.[/red] Usa /chats para ver disponibles.")
                continue
            if cmd.startswith('/close') and not cmd.startswith('/logout'):
                name = user_input[6:].strip() or None
                closed = self.chat_mgr.close_chat(name)
                if closed:
                    console.print(f"  [yellow]Chat '{closed}' cerrado.[/yellow] Actual: [bold cyan]{self.chat_mgr.current}[/bold cyan]")
                else:
                    console.print("  [red]No se pudo cerrar el chat.[/red]")
                continue

            await self.rate_limiter.wait_if_needed()
            try:
                with console.status(f"[bold green]{t('thinking')}"):
                    response = await self.client.chat(user_input)
                render_response(console, response)
            except Exception as e:
                render_error(console, str(e))

    async def run_one_shot(self, query: str):
        """Modo de una sola consulta"""
        self.client.default_session_name = "oneshot"
        try:
            response = await self.client.chat(query)
            console.print(response)
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            sys.exit(1)


def _handle_lang_command(config: dict):
    """Comando /lang para cambiar idioma en caliente."""
    console.print(f"\n  {t('lang_current', lang=LANGUAGES.get(get_language(), get_language()))}\n")
    console.print(f"  [bold]{t('lang_select')}[/bold]\n")
    for i, (code, name) in enumerate(LANGUAGES.items(), 1):
        marker = "[green]*[/green] " if code == get_language() else "  "
        console.print(f"  {marker}[cyan][{i}][/cyan] {name}")
    console.print()

    choice = Prompt.ask("  >", choices=["1", "2", "3"], default="1")
    lang_codes = list(LANGUAGES.keys())
    lang = lang_codes[int(choice) - 1]

    set_language(lang)
    config["lang"] = lang

    from cli.secure_config import save_config_secure
    config_path = config.get("_config_path", os.path.join(APPDATA_DIR, 'config.json'))
    save_config_secure(config, config_path)

    console.print(f"  [green]{t('lang_changed', lang=LANGUAGES[lang])}[/green]\n")


def main():
    parser = argparse.ArgumentParser(description="DeepSeek-Code: Asistente con herramientas avanzadas")
    parser.add_argument("-q", "--query", help="Consulta unica (modo one-shot)")
    parser.add_argument("--json", action="store_true", help="Output JSON estructurado")
    parser.add_argument("--agent", help="Ejecutar agente autonomo con meta")
    parser.add_argument("--delegate", help="Modo delegacion: tarea para DeepSeek como subordinado")
    parser.add_argument("--template", help="Archivo template con TODOs para rellenar (usado con --delegate)")
    parser.add_argument("--context", help="Archivo de contexto/estilo de referencia (usado con --delegate)")
    parser.add_argument("--feedback", help="Correccion de errores del intento anterior (usado con --delegate)")
    parser.add_argument("--max-retries", type=int, default=1, help="Reintentos auto si falla validacion (default: 1)")
    parser.add_argument("--no-validate", action="store_true", help="Desactivar validacion automatica de respuesta")
    parser.add_argument("--multi-step", dest="multi_step", help="Archivo JSON con plan multi-paso")
    parser.add_argument("--multi-step-inline", dest="multi_step_inline", help="JSON inline con plan multi-paso")
    parser.add_argument("--quantum", help="Modo quantum: delegacion paralela dual")
    parser.add_argument("--quantum-angles", dest="quantum_angles",
                        help="Angulos manuales separados por coma (ej: 'logica,render')")
    parser.add_argument("--multi", help="Modo multi-sesion: N instancias paralelas con roles")
    parser.add_argument("--roles", default="generate-review",
                        help="Preset de roles para multi-sesion (default: generate-review)")
    parser.add_argument("--instances", type=int, default=0,
                        help="Numero de instancias para multi-sesion (0=auto)")
    parser.add_argument("--pipeline", action="store_true",
                        help="Ejecutar multi-sesion en modo pipeline secuencial")
    parser.add_argument("--negotiate-skills", dest="negotiate_skills", action="store_true",
                        help="Dejar que DeepSeek elija sus propias skills (negociacion AI)")
    parser.add_argument("--converse", nargs="?", const="", default=None,
                        help="Modo conversacional multi-turno con DeepSeek")
    parser.add_argument("--converse-file", dest="converse_file",
                        help="Archivo JSON con mensajes para conversacion multi-turno")
    parser.add_argument("--project-context", dest="project_context",
                        help="Ruta a CLAUDE.md del proyecto (auto-detectado si no se pasa)")
    parser.add_argument("--requirements",
                        help="Documento de requisitos (.md/.txt) para generar plan multi-paso")
    parser.add_argument("--auto-execute", dest="auto_execute", action="store_true",
                        help="Ejecutar automaticamente el plan generado por --requirements")
    parser.add_argument("--health-report", dest="health_report", action="store_true",
                        help="Generar reporte predictivo de salud del proyecto")
    parser.add_argument("--config", help="Ruta al archivo de configuracion")

    # Session management
    parser.add_argument("--session", help="Nombre de sesion persistente para continuidad")
    parser.add_argument("--session-list", dest="session_list", action="store_true",
                        help="Listar todas las sesiones activas")
    parser.add_argument("--session-close", dest="session_close",
                        help="Cerrar una sesion especifica por nombre")
    parser.add_argument("--session-close-all", dest="session_close_all", action="store_true",
                        help="Cerrar todas las sesiones activas")
    parser.add_argument("--session-digest", dest="session_digest", action="store_true",
                        help="Output JSON detallado de todas las sesiones para routing")
    parser.add_argument("--transfer-from", dest="transfer_from",
                        help="Transferir conocimiento de otra sesion (usado con --session)")

    args = parser.parse_args()

    # Session management commands
    if args.session_list or args.session_close or args.session_close_all:
        from cli.session_commands import handle_session_commands
        handle_session_commands(args)
        return

    # Session digest: JSON compacto de todas las sesiones para routing
    if args.session_digest:
        import json as _json
        from deepseek_code.sessions.session_orchestrator import SessionOrchestrator
        from deepseek_code.client.session_chat import get_session_store
        from deepseek_code.sessions.knowledge_transfer import list_transferable_sessions
        store = get_session_store()
        orchestrator = SessionOrchestrator(store)
        digest = orchestrator.get_routing_digest()
        digest["transferable"] = list_transferable_sessions(store)
        print(_json.dumps(digest, ensure_ascii=False, indent=2))
        return

    # Intelligence: Requirements pipeline y health report
    if args.requirements:
        from cli.intel_runner import run_requirements
        run_requirements(args.requirements, args.json, args.config, args.auto_execute)
        return
    if args.health_report:
        from cli.intel_runner import run_health_report
        run_health_report(args.json, args.config, args.project_context)
        return

    # Modo multi-sesion (N instancias paralelas)
    if args.multi:
        from cli.multi_runner import run_multi
        run_multi(
            task=args.multi,
            template_path=args.template,
            roles_preset=args.roles,
            num_instances=args.instances,
            pipeline_mode=args.pipeline,
            json_mode=args.json,
            config_path=args.config,
            validate=not args.no_validate,
        )
        return

    # Modo conversacional multi-turno
    if args.converse is not None or args.converse_file:
        from cli.converse import run_converse
        run_converse(
            initial_message=args.converse if args.converse else None,
            converse_file=args.converse_file,
            json_mode=args.json,
            config_path=args.config,
            project_context_path=args.project_context,
            session_name=args.session,
            transfer_from=args.transfer_from,
        )
        return

    # Modo quantum (delegacion paralela dual)
    if args.quantum:
        from cli.quantum_runner import run_quantum
        run_quantum(
            task=args.quantum,
            template_path=args.template,
            angle_names=args.quantum_angles,
            json_mode=args.json,
            config_path=args.config,
            max_retries=args.max_retries,
            validate=not args.no_validate,
        )
        return

    # Modo multi-paso
    if args.multi_step or args.multi_step_inline:
        from cli.multi_step import run_multi_step
        run_multi_step(
            plan_path=args.multi_step,
            plan_inline=args.multi_step_inline,
            json_mode=args.json,
            config_path=args.config,
        )
        return

    # Modo programatico (one-shot, agent o delegate) — no necesita UI
    if args.query or args.agent or args.delegate:
        from cli.oneshot import run_oneshot, run_agent_oneshot, run_delegate_oneshot
        if args.delegate:
            run_delegate_oneshot(
                args.delegate,
                template_path=args.template,
                context_path=args.context,
                feedback=args.feedback,
                json_mode=args.json,
                config_path=args.config,
                max_retries=args.max_retries,
                validate=not args.no_validate,
                project_context_path=args.project_context,
                negotiate_skills=args.negotiate_skills,
                session_name=args.session,
                transfer_from=args.transfer_from,
            )
        elif args.agent:
            run_agent_oneshot(args.agent, json_mode=args.json, config_path=args.config)
        else:
            run_oneshot(args.query, json_mode=args.json, config_path=args.config)
        return

    # Modo interactivo — banner SIEMPRE primero (estilo Claude Code)
    config = load_config(args.config)

    # Cargar idioma desde config (si ya lo eligio antes)
    lang = config.get("lang")
    if lang:
        set_language(lang)

    from cli.ui_theme import render_ascii_banner
    render_ascii_banner(console)

    # Selector de idioma (solo primera vez, antes del login)
    from cli.onboarding import needs_onboarding, needs_language_selection, ask_language, run_onboarding
    if needs_language_selection(config):
        config = ask_language(config)

    if needs_onboarding(config):
        config = asyncio.run(run_onboarding(config))
        if config is None:
            sys.exit(0)

    app = DeepSeekCodeApp(config)
    asyncio.run(app.run_interactive())


if __name__ == "__main__":
    main()
