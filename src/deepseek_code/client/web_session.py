"""Sesion web de DeepSeek con Proof of Work via WebAssembly."""

import json
import base64
import struct
import time
import sys
from pathlib import Path
from typing import Union, Generator

import requests
import wasmtime

# Timeout en segundos sin recibir NINGUN chunk SSE antes de declarar stall.
# DeepSeek puede tardar en "pensar", pero siempre envia chunks de thinking.
# Si pasan 90s sin NADA, la conexion murio silenciosamente.
STALL_TIMEOUT_SECONDS = 90


class TokenExpiredError(Exception):
    """Bearer token expirado o invalido. Necesita re-login."""
    pass


class SessionDeadError(Exception):
    """Sesion de chat invalida o muerta. Se debe recrear."""
    pass


class StallDetectedError(Exception):
    """DeepSeek dejo de enviar datos por mas de STALL_TIMEOUT_SECONDS.

    Esto ocurre cuando la conexion SSE se congela silenciosamente.
    El caller debe reintentar el mismo mensaje.
    """
    pass


class DeepSeekWebSession:
    """
    Cliente para interactuar con la API web de DeepSeek usando cookies y Proof of Work.
    Requiere el archivo sha3_wasm_bg.wasm (proporcionado por DeepSeek).
    """

    def __init__(self, bearer_token: str, cookies: dict, wasm_path: Union[str, Path] = "sha3_wasm_bg.wasm"):
        self.bearer_token = bearer_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://chat.deepseek.com",
            "Referer": "https://chat.deepseek.com/",
        })
        self.session.cookies.update(cookies)

        # Cabeceras adicionales observadas en la web (pueden ser necesarias)
        self.extra_headers = {
            "x-hif-dliq": "9+au4vzMgrgmj4RrClblEgPFmaL9M45z25bxaU3mD6MJ97au0xxxh6Y=.Ofs9iag5WS/Bydqk",
            "x-hif-leim": "+uoffoEBcIDpucI8CaHSC/YiCCB4UKdN5HIttmPaO5/IVLWtJqsfPo4=.OGFWwVLqZ7MzZUPG"
        }

        # Cargar el modulo WASM
        self._init_wasm(wasm_path)

    def _init_wasm(self, wasm_path: Union[str, Path]):
        """Inicializa el motor wasmtime y carga las funciones necesarias."""
        wasm_path = Path(wasm_path)
        if not wasm_path.exists():
            raise FileNotFoundError(f"Archivo WASM no encontrado: {wasm_path}. Descargalo desde https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm")

        # Verificar que el archivo no este vacio
        if wasm_path.stat().st_size == 0:
            raise RuntimeError(f"Archivo WASM vacio: {wasm_path}. Vuelve a descargarlo.")

        self.engine = wasmtime.Engine()
        self.module = wasmtime.Module.from_file(self.engine, str(wasm_path))
        self.store = wasmtime.Store(self.engine)
        self.instance = wasmtime.Instance(self.store, self.module, [])

        # Obtener las funciones exportadas por el modulo
        exports = self.instance.exports(self.store)

        # Verificar que las funciones existan (nombres reales con prefijo "wasm_")
        if "wasm_solve" not in exports:
            raise RuntimeError(f"El archivo WASM no exporta la funcion 'wasm_solve'. Exportaciones disponibles: {list(exports.keys())}")
        if "wasm_deepseek_hash_v1" not in exports:
            raise RuntimeError(f"El archivo WASM no exporta la funcion 'wasm_deepseek_hash_v1'. Exportaciones disponibles: {list(exports.keys())}")

        self.solve_func = exports["wasm_solve"]
        self.hash_func = exports["wasm_deepseek_hash_v1"]
        self.wasm_memory = exports["memory"]
        self.wasm_alloc = exports.get("__wbindgen_export_0")  # malloc
        self.wasm_stack = exports.get("__wbindgen_add_to_stack_pointer")

    def _wasm_write_mem(self, offset: int, data: bytes):
        """Escribe bytes en la memoria WASM en el offset indicado."""
        import ctypes
        base_addr = ctypes.cast(self.wasm_memory.data_ptr(self.store), ctypes.c_void_p).value
        ctypes.memmove(base_addr + offset, data, len(data))

    def _wasm_read_mem(self, offset: int, length: int) -> bytes:
        """Lee bytes de la memoria WASM desde el offset indicado."""
        import ctypes
        base_addr = ctypes.cast(self.wasm_memory.data_ptr(self.store), ctypes.c_void_p).value
        return ctypes.string_at(base_addr + offset, length)

    def _wasm_encode_string(self, text: str) -> tuple:
        """Aloca memoria WASM y escribe un string UTF-8. Retorna (ptr, len)."""
        data = text.encode("utf-8")
        length = len(data)
        ptr_val = self.wasm_alloc(self.store, length, 1)
        ptr = int(ptr_val.value) if hasattr(ptr_val, "value") else int(ptr_val)
        self._wasm_write_mem(ptr, data)
        return ptr, length

    def get_challenge(self) -> dict:
        """Obtiene un nuevo challenge desde el endpoint /create_pow_challenge."""
        url = "https://chat.deepseek.com/api/v0/chat/create_pow_challenge"
        resp = self.session.post(url, json={"target_path": "/api/v0/chat/completion"})
        if resp.status_code == 401:
            raise TokenExpiredError("Bearer token expirado. Usa /login para renovar.")
        if resp.status_code == 403:
            raise TokenExpiredError("Acceso denegado. Token invalido o cuenta bloqueada.")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Error al obtener challenge: {data}")
        return data["data"]["biz_data"]["challenge"]

    def solve_challenge(self, challenge: dict) -> int:
        """Resuelve el Proof of Work usando wasm_solve.

        Signatura WASM (wasm-bindgen):
            wasm_solve(retptr, challenge_ptr, challenge_len, prefix_ptr, prefix_len, difficulty)
        Donde:
            - retptr: puntero de retorno en el stack (16 bytes)
            - challenge/prefix: strings UTF-8 alocados con __wbindgen_export_0
            - difficulty: f64
        Resultado en retptr:
            - [0:4] status (i32): 0 = fallo, != 0 = exito
            - [8:16] value (f64): el nonce encontrado
        """
        challenge_str = challenge["challenge"]
        prefix = f"{challenge['salt']}_{challenge['expire_at']}_"
        difficulty = float(challenge["difficulty"])

        # Reservar 16 bytes en el stack para el resultado
        retptr = self.wasm_stack(self.store, -16)

        try:
            # Alocar y escribir strings en memoria WASM
            challenge_ptr, challenge_len = self._wasm_encode_string(challenge_str)
            prefix_ptr, prefix_len = self._wasm_encode_string(prefix)

            # Llamar wasm_solve(retptr, challenge_ptr, challenge_len, prefix_ptr, prefix_len, difficulty)
            self.solve_func(
                self.store,
                retptr,
                challenge_ptr, challenge_len,
                prefix_ptr, prefix_len,
                difficulty
            )

            # Leer resultado: status (i32) en retptr[0:4], value (f64) en retptr[8:16]
            status_bytes = self._wasm_read_mem(retptr, 4)
            status = struct.unpack("<i", status_bytes)[0]

            if status == 0:
                raise RuntimeError("wasm_solve retorno status=0 (fallo al resolver PoW)")

            value_bytes = self._wasm_read_mem(retptr + 8, 8)
            value = struct.unpack("<d", value_bytes)[0]
            return int(value)
        finally:
            # Restaurar el stack pointer
            self.wasm_stack(self.store, 16)

    def prepare_pow_header(self, challenge: dict, answer: int) -> str:
        """Construye la cabecera x-ds-pow-response en Base64."""
        pow_response = {
            "algorithm": challenge["algorithm"],
            "challenge": challenge["challenge"],
            "salt": challenge["salt"],
            "answer": answer,
            "signature": challenge["signature"],
            "target_path": challenge["target_path"]
        }
        json_str = json.dumps(pow_response, separators=(',', ':'))
        return base64.b64encode(json_str.encode()).decode()

    def create_chat_session(self) -> str:
        """Crea una nueva sesion de chat y retorna su UUID."""
        url = "https://chat.deepseek.com/api/v0/chat_session/create"
        resp = self.session.post(url, json={})
        if resp.status_code == 401:
            raise TokenExpiredError("Bearer token expirado al crear sesion.")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise SessionDeadError(f"Error creando sesion de chat: {data}")
        return data["data"]["biz_data"]["id"]

    def send_message(self, message: str, pow_header: str, chat_session_id: str = None,
                     thinking_enabled: bool = False,
                     parent_message_id=None) -> Generator[str, None, None]:
        """Envia un mensaje con la cabecera PoW. Retorna generador de tokens (streaming SSE).

        Args:
            parent_message_id: ID del mensaje padre para continuidad de conversacion.
                Si es None, DeepSeek usa el ultimo mensaje de la sesion.

        Raises:
            StallDetectedError: Si no se recibe ningun chunk SSE en STALL_TIMEOUT_SECONDS.
            TokenExpiredError: Si el bearer token expiro o es invalido.
        """
        if not chat_session_id:
            chat_session_id = self.create_chat_session()

        url = "https://chat.deepseek.com/api/v0/chat/completion"
        headers = {**self.session.headers, **self.extra_headers, "x-ds-pow-response": pow_header}
        payload = {
            "chat_session_id": chat_session_id,
            "parent_message_id": parent_message_id,
            "prompt": message,
            "ref_file_ids": [],
            "thinking_enabled": thinking_enabled,
            "search_enabled": True,
        }

        self._last_message_id = None

        # timeout=(connect, read) — read timeout actua como per-chunk timeout.
        # Si no llega NINGUN dato en STALL_TIMEOUT_SECONDS, requests lanza
        # requests.exceptions.ReadTimeout → convertimos a StallDetectedError.
        try:
            with self.session.post(
                url, headers=headers, json=payload, stream=True,
                timeout=(30, STALL_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status_code == 401:
                    raise TokenExpiredError("Bearer token expirado durante envio. Usa /login para renovar.")
                if resp.status_code == 403:
                    raise TokenExpiredError("Acceso denegado durante envio. Token invalido.")
                resp.raise_for_status()
                last_event = ""
                stream_mode = "init"  # "init" -> "thinking" -> "content"

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8", errors="replace")

                    if line_str.startswith("event: "):
                        last_event = line_str[7:].strip()
                        if last_event == "finish":
                            break
                        continue

                    if line_str.startswith("data: "):
                        raw = line_str[6:]
                        if raw == "[DONE]" or raw == "{}":
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # Capturar response_message_id del chunk metadata inicial
                        if "response_message_id" in chunk:
                            self._last_message_id = chunk["response_message_id"]

                        if "v" not in chunk:
                            continue

                        path = chunk.get("p", "")
                        val = chunk["v"]

                        # Capturar message_id del objeto response inicial
                        if isinstance(val, dict) and "response" in val:
                            resp_obj = val["response"]
                            if isinstance(resp_obj, dict) and "message_id" in resp_obj:
                                self._last_message_id = resp_obj["message_id"]
                            continue

                        # Track stream mode transitions
                        if path == "response/thinking_content":
                            stream_mode = "thinking"
                            continue
                        if path == "response/content":
                            stream_mode = "content"
                            if isinstance(val, str):
                                yield val
                            continue

                        # Ignore all other non-empty paths
                        if path:
                            continue

                        # For p="" chunks, only yield if we're in content mode
                        if stream_mode != "content":
                            continue

                        # Extraer texto de respuesta
                        if isinstance(val, str):
                            yield val
                        elif isinstance(val, dict):
                            content = val.get("content", "")
                            if content:
                                yield content

        except requests.exceptions.ReadTimeout:
            print(
                f"  [STALL] DeepSeek no envio datos en {STALL_TIMEOUT_SECONDS}s. "
                f"Conexion congelada detectada.",
                file=sys.stderr,
            )
            raise StallDetectedError(
                f"DeepSeek dejo de responder por {STALL_TIMEOUT_SECONDS}s. "
                f"La conexion SSE se congelo silenciosamente."
            )
        except requests.exceptions.ConnectionError as e:
            print(f"  [STALL] Conexion perdida: {e}", file=sys.stderr)
            raise StallDetectedError(f"Conexion perdida durante streaming: {e}")

    def _chat_internal(self, message: str, thinking_enabled: bool = False,
                       parent_message_id=None) -> str:
        """Logica interna de chat: challenge + solve + send."""
        challenge = self.get_challenge()
        answer = self.solve_challenge(challenge)
        pow_header = self.prepare_pow_header(challenge, answer)

        if not hasattr(self, '_chat_session_id') or not self._chat_session_id:
            self._chat_session_id = self.create_chat_session()

        full_response = ""
        for token in self.send_message(
            message, pow_header, self._chat_session_id,
            thinking_enabled, parent_message_id
        ):
            full_response += token
        return full_response

    def chat(self, message: str, thinking_enabled: bool = False,
             parent_message_id=None, max_stall_retries: int = 3) -> str:
        """Metodo de alto nivel con auto-recovery de sesion muerta y stall detection.

        Detecta y reintenta automaticamente:
        - StallDetectedError: stream SSE congelado (90s sin datos)
        - Respuesta vacia: stream termino limpiamente pero sin contenido
          (DeepSeek penso y cerro sin generar respuesta)

        Reintenta hasta max_stall_retries veces con sesion nueva.
        """
        let_attempts = 0
        let_last_error = None

        while let_attempts <= max_stall_retries:
            try:
                let_response = self._chat_internal(message, thinking_enabled, parent_message_id)

                # Detectar respuesta vacia: stream termino sin producir contenido.
                # Esto pasa cuando DeepSeek piensa y cierra el stream sin responder,
                # o cuando hay un error silencioso en el SSE.
                if not let_response or not let_response.strip():
                    let_attempts += 1
                    if let_attempts <= max_stall_retries:
                        print(
                            f"  [EMPTY] Respuesta vacia detectada. "
                            f"Reintentando ({let_attempts}/{max_stall_retries})...",
                            file=sys.stderr,
                        )
                        self._chat_session_id = self.create_chat_session()
                        continue
                    else:
                        print(
                            f"  [EMPTY] Agotados {max_stall_retries} reintentos. "
                            f"DeepSeek retorna respuestas vacias.",
                            file=sys.stderr,
                        )
                        raise StallDetectedError(
                            "DeepSeek retorno respuesta vacia tras "
                            f"{max_stall_retries} reintentos."
                        )

                return let_response

            except StallDetectedError as e:
                let_attempts += 1
                let_last_error = e
                if let_attempts <= max_stall_retries:
                    print(
                        f"  [STALL] Reintentando ({let_attempts}/{max_stall_retries})...",
                        file=sys.stderr,
                    )
                    self._chat_session_id = self.create_chat_session()
                else:
                    print(
                        f"  [STALL] Agotados {max_stall_retries} reintentos. "
                        f"DeepSeek no responde.",
                        file=sys.stderr,
                    )
                    raise
            except (SessionDeadError, RuntimeError) as e:
                err_msg = str(e).lower()
                if "session" in err_msg or "chat_session" in err_msg:
                    self._chat_session_id = self.create_chat_session()
                    return self._chat_internal(message, thinking_enabled, parent_message_id)
                raise

        raise let_last_error

    @property
    def last_message_id(self) -> str:
        """ID del ultimo mensaje de respuesta (para continuidad)."""
        return getattr(self, '_last_message_id', None)
