"""Tool calling simulado por texto para modo web de DeepSeek.

El modo web no tiene API de tool calling nativa. Este modulo inyecta
instrucciones de formato en el prompt para que DeepSeek responda con
bloques JSON cuando quiera usar una herramienta, y luego parsea y
ejecuta esas llamadas.
"""

import json
import os
import re
from typing import List, Dict, Optional, Tuple


def build_tools_prompt(tools: List[Dict]) -> str:
    """Construye la seccion de herramientas para inyectar en el prompt."""
    if not tools:
        return ""

    home_escaped = os.path.expanduser("~").replace("\\", "\\\\")
    desktop_escaped = os.path.expanduser("~/Desktop").replace("\\", "\\\\")

    lines = [
        "\n\n--- HERRAMIENTAS DISPONIBLES ---",
        "REGLA CRITICA: DEBES usar herramientas para CUALQUIER pregunta que pueda responderse",
        "consultando el sistema. NUNCA describas lo que podrias hacer — HAZLO con herramientas.",
        "",
        "FORMATO: Para invocar herramientas, usa UN bloque tool_call con un array JSON:",
        "```tool_call",
        '[{"tool": "nombre", "args": {"param": "valor"}}]',
        "```",
        "",
        "Para MULTIPLES herramientas en una respuesta (recomendado — mas eficiente):",
        "```tool_call",
        "[",
        '  {"tool": "herramienta1", "args": {"param": "valor"}},',
        '  {"tool": "herramienta2", "args": {"param": "valor"}}',
        "]",
        "```",
        "",
        "REGLAS:",
        "1. Usa UN solo bloque ```tool_call``` por respuesta con TODAS las herramientas dentro.",
        "2. Despues de recibir el resultado, RESUME la informacion en texto natural.",
        "   NUNCA copies el JSON crudo en tu respuesta. Sintetiza los datos relevantes.",
        "3. SOLO responde sin tool_call si es una pregunta puramente conversacional.",
        "4. Puedes usar hasta 8 herramientas por bloque. Puedes repetir la misma (ej: multiples write_file).",
        "5. Para write_file con archivos grandes, escribe TODO el contenido en UNA sola llamada.",
        "",
        "EJEMPLOS de cuando DEBES usar herramientas:",
        "",
        "Usuario: 'lista mis archivos' →",
        "```tool_call",
        '[{"tool": "list_directory", "args": {"path": "' + desktop_escaped + '"}}]',
        "```",
        "",
        "Usuario: 'que hora es' →",
        "```tool_call",
        '[{"tool": "run_command", "args": {"command": "powershell Get-Date"}}]',
        "```",
        "",
        "Usuario: 'crea un proyecto con 3 archivos' → (multiples herramientas en un bloque)",
        "```tool_call",
        "[",
        '  {"tool": "write_file", "args": {"path": "' + desktop_escaped + '\\\\proyecto\\\\index.html", "content": "..."}},',
        '  {"tool": "write_file", "args": {"path": "' + desktop_escaped + '\\\\proyecto\\\\style.css", "content": "..."}},',
        '  {"tool": "write_file", "args": {"path": "' + desktop_escaped + '\\\\proyecto\\\\app.js", "content": "..."}}',
        "]",
        "```",
        ""
    ]

    for t in tools:
        name = t["name"]
        desc = t["description"]
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        params_desc = []
        for pname, pinfo in props.items():
            ptype = pinfo.get("type", "string")
            pdesc = pinfo.get("description", "")
            req_mark = " (REQUERIDO)" if pname in required else ""
            params_desc.append(f"    - {pname} ({ptype}){req_mark}: {pdesc}")

        lines.append(f"**{name}**: {desc}")
        if params_desc:
            lines.append("  Parametros:")
            lines.extend(params_desc)
        lines.append("")

    lines.append("--- FIN HERRAMIENTAS ---\n")
    return "\n".join(lines)


def build_web_prompt(system_message: str, conversation: List[Dict], tools_prompt: str) -> str:
    """Construye el prompt completo para enviar al modo web.

    Incluye: system message + info del sistema + herramientas + historial.
    """
    import platform
    home = os.path.expanduser("~")
    sys_info = (
        f"\n[Info del sistema: {platform.system()} {platform.release()}, "
        f"usuario: {os.environ.get('USERNAME', 'desconocido')}, "
        f"home: {home}]\n"
    )

    parts = [system_message, sys_info]

    if tools_prompt:
        parts.append(tools_prompt)

    # Agregar historial (limitar a ultimos 100 mensajes — 1M contexto lo permite)
    recent = [m for m in conversation if m.get("role") != "system"]
    if len(recent) > 100:
        recent = recent[-100:]

    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""

        if role == "user":
            parts.append(f"\nUsuario: {content}")
        elif role == "assistant":
            parts.append(f"\nAsistente: {content}")
        elif role == "tool_result":
            parts.append(f"\nResultado de herramienta: {content}")

    return "\n".join(parts)


def extract_tool_calls(response: str) -> Tuple[List[Dict], str]:
    """Extrae bloques tool_call de la respuesta y retorna (calls, texto_limpio).

    Busca bloques:
    ```tool_call
    {"tool": "...", "args": {...}}
    ```

    DEDUPLICACION: DeepSeek a veces genera multiples bloques identicos.
    Solo se ejecuta la primera instancia de cada (tool, args) unico.

    Retorna:
        - Lista de dicts con 'tool' y 'args' (deduplicados)
        - Texto de la respuesta sin los bloques tool_call
    """
    raw_calls = []
    # Patron para bloques ```tool_call ... ```
    pattern = r'```tool_call\s*\n(.*?)\n```'
    matches = re.findall(pattern, response, re.DOTALL)

    def _append_call(item):
        """Extrae tool+args de un dict y lo agrega a raw_calls."""
        if isinstance(item, dict) and "tool" in item:
            raw_calls.append({
                "tool": item["tool"],
                "args": item.get("args", item.get("arguments", {}))
            })

    for match in matches:
        try:
            data = json.loads(match.strip())
            if isinstance(data, list):
                # Array de tool calls: [{tool:..., args:...}, ...]
                for item in data:
                    _append_call(item)
            else:
                _append_call(data)
        except json.JSONDecodeError:
            # Intentar extraer JSON parcial
            try:
                # A veces el modelo pone texto extra
                json_match = re.search(r'\{.*\}', match, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    _append_call(data)
            except (json.JSONDecodeError, AttributeError):
                pass

    # Deduplicar: solo mantener la primera instancia de cada (tool, args)
    seen = set()
    calls = []
    for call in raw_calls:
        key = json.dumps(call, sort_keys=True)
        if key not in seen:
            seen.add(key)
            calls.append(call)

    if len(raw_calls) > len(calls):
        print(f"  [dedup] {len(raw_calls)} tool_calls -> {len(calls)} unicos")

    # Limpiar respuesta: quitar bloques tool_call
    clean_text = re.sub(r'```tool_call\s*\n.*?\n```', '', response, flags=re.DOTALL).strip()

    return calls, clean_text


def format_tool_result(tool_name: str, result) -> str:
    """Formatea el resultado de una herramienta para inyectar en el prompt."""
    if isinstance(result, dict):
        result_str = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result_str = str(result)

    # Truncar resultados extremadamente largos (120K chars ~ 30K tokens, ~3% del contexto 1M)
    if len(result_str) > 120000:
        result_str = result_str[:120000] + "\n... [resultado truncado, usa read_file con max_lines para ver mas]"

    return f"Resultado de `{tool_name}`:\n```\n{result_str}\n```"


def clean_final_response(response: str) -> str:
    """Limpia la respuesta final quitando JSON crudo y bloques de resultados repetidos.

    DeepSeek a veces copia los resultados de herramientas en su respuesta final
    en multiples formatos. Esta funcion los detecta y elimina agresivamente.
    """
    cleaned = response

    # 1. Quitar secciones completas "Resultado de herramienta:" con todo su contenido
    #    Matchea desde "Resultado de herramienta:" hasta "Asistente:" o doble newline
    #    seguido de texto normal (no JSON)
    cleaned = re.sub(
        r'Resultado de herramienta:.*?(?=(?:^[A-ZÁÉÍÓÚ¡¿]|\Z))',
        '', cleaned, flags=re.DOTALL | re.MULTILINE
    )

    # 2. Quitar bloques ``` con contenido largo (>300 chars)
    def _replace_long_block(match):
        if len(match.group(1)) > 300:
            return ""
        return match.group(0)

    cleaned = re.sub(
        r'```[a-z]*\s*\n(.*?)\n```',
        _replace_long_block, cleaned, flags=re.DOTALL
    )

    # 3. Quitar "Resultado de `tool`:" con cualquier contenido hasta linea vacia
    cleaned = re.sub(
        r'Resultado de `\w+`:.*?(?=\n\n|\Z)',
        '', cleaned, flags=re.DOTALL
    )

    # 4. Quitar JSON inline: {"content":... o {"stdout":... suelto en texto
    cleaned = re.sub(
        r'\{"\w+":\s*[\{\["].*?\}(?:\})?',
        '', cleaned, flags=re.DOTALL
    )

    # 5. Quitar lineas que empiezan con "Asistente:" (DeepSeek se cita)
    cleaned = re.sub(r'^Asistente:\s*', '', cleaned, flags=re.MULTILINE)

    # 6. Quitar "Paso N:" headers internos
    cleaned = re.sub(r'^Paso \d+:.*$', '', cleaned, flags=re.MULTILINE)

    # 7. Limpiar lineas vacias multiples
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip()


async def run_agent_web(web_session, mcp_server, system_prompt: str,
                        user_message: str, tools: list, max_steps: int = 50,
                        continue_parent_id: int = None) -> str:
    """Ejecuta un paso de agente en modo web con tool calling simulado.

    Usa Phase 1 (identidad + herramientas) con message chaining via parent_message_id.
    DeepSeek PRIMERO confirma su identidad con "DEEPSEEK CODE ACTIVADO" y solo
    DESPUES recibe el mensaje del usuario.

    Flow (primera llamada):
    1. Phase 1: system_prompt + tools → "DEEPSEEK CODE ACTIVADO"
    2. User message (chained via parent_id)
    3. Tool loop: response → extract tools → execute → send results (chained)

    Flow (continuacion — continue_parent_id proporcionado):
    1. Skip Phase 1 (ya establecida en la sesion existente)
    2. User message (chained via continue_parent_id)
    3. Tool loop (igual)

    Usado por AgentEngine y _chat_with_system_web().
    """
    import asyncio
    import sys
    from ..server.protocol import MCPRequest, MCPMethod
    from .web_session import TokenExpiredError, StallDetectedError

    if continue_parent_id is not None:
        # --- Continuacion: reusar sesion existente, saltar Phase 1 ---
        let_parent_id = continue_parent_id
        print(f"  [agente] Continuando sesion (parent_id={let_parent_id})", file=sys.stderr)
    else:
        # --- Crear sesion fresca para este agente ---
        let_chat_session_id = web_session.create_chat_session()
        web_session._chat_session_id = let_chat_session_id

        # --- Phase 1: Identidad + herramientas → "DEEPSEEK CODE ACTIVADO" ---
        tools_prompt = build_tools_prompt(tools) if tools else ""
        init_prompt = system_prompt + tools_prompt + (
            "\n\nResponde UNICAMENTE 'DEEPSEEK CODE ACTIVADO' para confirmar "
            "que entendiste tu identidad y herramientas."
        )

        print(f"  [agente] Phase 1: Enviando identidad + herramientas...", file=sys.stderr)
        try:
            _init_response = await asyncio.get_event_loop().run_in_executor(
                None, web_session.chat, init_prompt, True, None,
            )
        except TokenExpiredError as e:
            return f"[Error de sesion] {e}. Ejecuta /login para renovar."
        except StallDetectedError as e:
            print(f"  [agente] STALL en Phase 1: {e}", file=sys.stderr)
            return (
                "[Error] DeepSeek se congelo durante Phase 1 (identidad). "
                "Los reintentos automaticos se agotaron. "
                "Ejecuta el comando de nuevo."
            )

        let_parent_id = web_session.last_message_id
        print(f"  [agente] Phase 1: DeepSeek confirmo identidad (parent_id={let_parent_id})", file=sys.stderr)

    # --- User message + tool loop (chained via parent_id) ---
    prompt = user_message

    for step in range(max_steps):
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, web_session.chat, prompt, True, let_parent_id,
            )
        except TokenExpiredError as e:
            return f"[Error de sesion] {e}. Ejecuta /login para renovar."
        except StallDetectedError as e:
            print(
                f"  [agente] STALL en iter={step+1}: {e}",
                file=sys.stderr,
            )
            return (
                f"[Error] DeepSeek se congelo en la iteracion {step+1}. "
                f"Los reintentos automaticos se agotaron. "
                f"Ejecuta el comando de nuevo."
            )

        # Capturar message_id para continuidad
        let_parent_id = web_session.last_message_id

        # Extraer tool calls
        tool_calls, clean_text = extract_tool_calls(response)

        if not tool_calls:
            # Respuesta final — limpiar si hubo tool calls previos
            cleaned = clean_final_response(response) if step > 0 else response
            return cleaned

        # Ejecutar herramientas
        results = []
        for idx, call in enumerate(tool_calls):
            tool_name = call["tool"]
            arguments = call["args"]
            tool_request = MCPRequest(
                id=f"agent_{step}_{idx}_{tool_name}",
                method=MCPMethod.TOOLS_CALL,
                params={"name": tool_name, "arguments": arguments}
            )
            tool_response = await mcp_server.handle_request(tool_request)

            if hasattr(tool_response, 'error'):
                result_str = f"Error: {tool_response.error.message}"
            else:
                result = tool_response.result
                result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)

            results.append(format_tool_result(tool_name, result_str))
            print(
                f"  [agente] iter={step+1}/{max_steps} {tool_name} -> {len(result_str)} chars",
                file=sys.stderr,
            )

        # Siguiente prompt son los resultados (encadenados via parent_id)
        prompt = "\n".join(results)

    return "Se alcanzo el numero maximo de iteraciones en modo agente web."
