"""CLI commands for session management.

Handles --session-list, --session-close, --session-close-all.
"""

import json
import sys


def handle_session_commands(args):
    """Dispatch session management commands."""
    from deepseek_code.client.session_chat import (
        list_sessions_json, close_session, close_all_sessions,
    )

    if args.session_close_all:
        result = close_all_sessions()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Sesiones cerradas: {result['closed_count']}")
        return

    if args.session_close:
        result = close_session(args.session_close)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result["success"]:
                print(f"Sesion '{args.session_close}' cerrada.")
            else:
                print(f"Error: {result['error']}", file=sys.stderr)
        return

    if args.session_list:
        result = list_sessions_json()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            active = result["sessions"]
            if not active:
                print("No hay sesiones activas.")
            else:
                print(f"\nSesiones activas ({len(active)}):\n")
                for s in active:
                    print(
                        f"  {s['name']:<20} "
                        f"msgs: {s['messages']:<4} "
                        f"ultima: {s['last_active']}  "
                        f"{'[system OK]' if s['system_sent'] else '[nueva]'}"
                    )
                print()
