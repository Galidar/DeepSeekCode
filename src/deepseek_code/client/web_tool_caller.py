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
    let_empty_retries = 0
    let_max_empty_retries = 2
    let_error_tracker = {}  # {error_pattern_normalizado: count}
    let_max_repeat_errors = 3
    let_last_successful_tools = []  # [(tool_name, result_summary), ...]
    let_stall_nudge_count = 0  # Nudges enviados tras stall en reads
    let_max_stall_nudges = 2   # Max nudges antes de rendirse
    let_max_tools_per_iter = 5  # Limitar tools por iteracion

    for step in range(max_steps):
        try:
            # max_stall_retries=0: NO crear sesiones nuevas en stalls.
            # La logica de recovery la manejamos aqui con nudges inteligentes.
            response = await asyncio.get_event_loop().run_in_executor(
                None, web_session.chat, prompt, True, let_parent_id, 0,
            )
        except TokenExpiredError as e:
            return f"[Error de sesion] {e}. Ejecuta /login para renovar."
        except StallDetectedError as e:
            # --- Stall recovery inteligente con nudges ---
            # Preservar parent_id del response stalled (DeepSeek asigno msg_id
            # aunque el contenido quedo vacio — el contexto sigue en la sesion)
            if web_session.last_message_id:
                let_parent_id = web_session.last_message_id

            # Clasificar: stall despues de reads vs despues de writes
            let_write_tools = ("write_file", "run_command", "make_directory",
                               "move_file", "copy_file")
            let_had_any_writes = any(
                t[0] in let_write_tools for t in let_last_successful_tools
            )

            if not let_had_any_writes and let_stall_nudge_count < let_max_stall_nudges:
                # Stall DESPUES de reads — DeepSeek penso 30s y no pudo generar
                # la respuesta con multiples write_file. Nudge: pedir UNO a la vez.
                let_stall_nudge_count += 1
                print(
                    f"  [agente] STALL despues de {len(let_last_successful_tools)} reads. "
                    f"Nudge #{let_stall_nudge_count}/{let_max_stall_nudges}...",
                    file=sys.stderr,
                )
                prompt = (
                    "Tu respuesta anterior se corto (el stream termino sin contenido). "
                    "Los archivos que leiste ya estan en tu contexto de conversacion. "
                    "Para evitar sobrecarga, escribe los archivos DE A UNO. "
                    "Genera un bloque ```tool_call``` con UN SOLO write_file. "
                    "Empieza con package.json."
                )
                continue

            # Stall despues de writes, o nudges agotados → resumen sintetico
            if let_last_successful_tools:
                let_summary_parts = []
                for tname, tresult in let_last_successful_tools:
                    let_summary_parts.append(f"- {tname}: {tresult}")
                let_synthetic = (
                    "Herramientas ejecutadas en esta sesion:\n"
                    + "\n".join(let_summary_parts)
                    + "\n\nResumen de progreso parcial."
                )
                print(
                    f"  [agente] STALL en iter={step+1} tras {len(let_last_successful_tools)} tools OK. "
                    f"Retornando resumen sintetico.",
                    file=sys.stderr,
                )
                return let_synthetic
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

        # Detectar respuesta vacia/muerta: el stream termino pero sin contenido util.
        # chat() ya reintenta internamente, pero si llega aqui vacio, enviamos
        # un nudge para despertar a DeepSeek.
        if not response or not response.strip():
            let_empty_retries += 1
            if let_empty_retries <= let_max_empty_retries:
                print(
                    f"  [agente] Respuesta vacia en iter={step+1}. "
                    f"Enviando nudge ({let_empty_retries}/{let_max_empty_retries})...",
                    file=sys.stderr,
                )
                prompt = (
                    "Tu respuesta anterior llego vacia. "
                    "Continua con la tarea. Usa herramientas si las necesitas."
                )
                continue
            else:
                print(
                    f"  [agente] {let_max_empty_retries} respuestas vacias consecutivas. "
                    f"Conversacion muerta.",
                    file=sys.stderr,
                )
                return (
                    "[Error] DeepSeek dejo de responder "
                    f"({let_max_empty_retries} respuestas vacias consecutivas). "
                    "Ejecuta el comando de nuevo."
                )
        else:
            let_empty_retries = 0  # Reset si llega una respuesta valida
            let_stall_nudge_count = 0  # Reset nudges en respuesta exitosa

        # Extraer tool calls
        tool_calls, clean_text = extract_tool_calls(response)

        if not tool_calls:
            # --- Detector de alucinaciones ---
            # Si DeepSeek dice "completado/exitosa/sin errores" pero NO ejecuto
            # herramientas de escritura, esta alucinando — forzar uso de tools.
            let_completion_keywords = [
                "completado", "exitosa", "sin errores", "correctamente",
                "he creado", "he replicado", "he copiado", "he ejecutado",
                "npm install", "npm run build", "npm run dev",
            ]
            let_response_lower = response.lower()
            let_claims_completion = any(kw in let_response_lower for kw in let_completion_keywords)
            let_had_writes = any(
                t[0] in ("write_file", "run_command", "make_directory", "move_file", "copy_file")
                for t in let_last_successful_tools
            )

            if let_claims_completion and not let_had_writes and step < 3:
                print(
                    f"  [agente] !! ALUCINACION detectada en iter={step+1}: "
                    f"dice 'completado' pero 0 herramientas de escritura ejecutadas. "
                    f"Enviando correccion.",
                    file=sys.stderr,
                )
                prompt = (
                    "ATENCION: Tu respuesta anterior DESCRIBIO acciones pero NO las ejecutaste. "
                    "No creaste ningun archivo ni ejecutaste ningun comando. "
                    "DEBES usar herramientas (write_file, run_command, etc.) para realizar "
                    "las acciones. NO describas lo que harias — HAZLO con tool_call. "
                    "Continua con la tarea ahora."
                )
                continue

            # Respuesta final — limpiar si hubo tool calls previos
            cleaned = clean_final_response(response) if step > 0 else response
            return cleaned

        # Ejecutar herramientas (limitar por iteracion para reducir presion de contexto)
        let_pending_calls = []
        if len(tool_calls) > let_max_tools_per_iter:
            let_pending_calls = tool_calls[let_max_tools_per_iter:]
            tool_calls = tool_calls[:let_max_tools_per_iter]
            print(
                f"  [agente] Limitando a {let_max_tools_per_iter} de "
                f"{let_max_tools_per_iter + len(let_pending_calls)} tools en esta iter",
                file=sys.stderr,
            )

        results = []
        let_iter_errors = 0
        let_iter_ok = 0
        let_last_successful_tools = []  # Reset para esta iteracion
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
                let_iter_errors += 1
                # Rastrear errores repetitivos (normalizar quitando paths)
                let_err_key = re.sub(r'[A-Z]:\\[^\s]+', '<path>', tool_response.error.message)
                let_err_key = re.sub(r'/[^\s]+/', '<path>/', let_err_key)[:80]
                let_error_tracker[let_err_key] = let_error_tracker.get(let_err_key, 0) + 1
            else:
                result = tool_response.result
                result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
                let_iter_ok += 1
                # Rastrear tools exitosos para stall recovery
                let_tool_summary = result_str[:100] + ("..." if len(result_str) > 100 else "")
                let_last_successful_tools.append((tool_name, let_tool_summary))

            results.append(format_tool_result(tool_name, result_str))
            print(
                f"  [agente] iter={step+1}/{max_steps} {tool_name} -> {len(result_str)} chars",
                file=sys.stderr,
            )

        # Resumen de iteracion
        print(
            f"  [agente] === iter {step+1}/{max_steps}: "
            f"{len(tool_calls)} tools ({let_iter_ok} OK, {let_iter_errors} err) ===",
            file=sys.stderr,
        )

        # Notificar tools pendientes (si se limito la iteracion)
        prompt = "\n".join(results)
        if let_pending_calls:
            let_pending_names = [c["tool"] for c in let_pending_calls]
            prompt += (
                f"\n\nNOTA: Se ejecutaron {len(tool_calls)} de "
                f"{len(tool_calls) + len(let_pending_calls)} herramientas. "
                f"Pendientes: {', '.join(let_pending_names)}. "
                f"Genera las pendientes en tu siguiente respuesta."
            )

        # Detectar errores repetitivos — inyectar correccion a DeepSeek
        let_repeated = {k: v for k, v in let_error_tracker.items()
                        if v >= let_max_repeat_errors}
        if let_repeated:
            let_correction = "\n\nADVERTENCIA — Errores repetitivos detectados:\n"
            for err_pattern, err_count in let_repeated.items():
                let_correction += f"  - ({err_count}x) {err_pattern}\n"
                print(
                    f"  [agente] !! Error repetido ({err_count}x): {err_pattern}",
                    file=sys.stderr,
                )
            let_correction += (
                "CAMBIA DE ESTRATEGIA. No repitas la misma operacion que falla. "
                "Si necesitas crear un directorio, usa make_directory primero. "
                "Si un archivo no existe, verifica con list_directory antes de operar."
            )
            prompt += let_correction

    return "Se alcanzo el numero maximo de iteraciones en modo agente web."
