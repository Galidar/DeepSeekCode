"""Herramienta para gestionar API keys y sesiones web de DeepSeek desde la consola."""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any

import aiofiles
from openai import AsyncOpenAI

from ..server.tool import BaseTool
from ..auth.web_login import run_login, validate_session, PYQT_AVAILABLE

class ManageKeysTool(BaseTool):
    """Gestiona las credenciales de DeepSeek: API key o sesion web."""

    def __init__(self, config_path: str, deepseek_client=None):
        self.config_path = Path(config_path).expanduser().resolve()
        self.deepseek_client = deepseek_client
        super().__init__(
            name="manage_keys",
            description=(
                "Gestiona credenciales de DeepSeek. "
                "Acciones: status (ver estado), set_api_key (guardar API key), "
                "test_api_key (probar API key), web_login (login con cuenta), "
                "set_bearer_token (guardar token), web_test (probar sesion web), "
                "web_logout (eliminar credenciales web), instructions (ver guia)."
            )
        )

    def _build_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "set_api_key",
                        "test_api_key",
                        "web_login",
                        "set_bearer_token",
                        "web_test",
                        "web_logout",
                        "instructions"
                    ],
                    "description": (
                        "Accion a realizar. "
                        "status: ver credenciales configuradas. "
                        "set_api_key: guardar nueva API key (requiere new_key). "
                        "test_api_key: verificar que la API key funciona. "
                        "web_login: abrir ventana para capturar cookies de deepseek.com. "
                        "set_bearer_token: guardar token Bearer manualmente (requiere new_key). "
                        "web_test: verificar que la sesion web funciona. "
                        "web_logout: eliminar credenciales web. "
                        "instructions: ver guia paso a paso."
                    )
                },
                "new_key": {
                    "type": "string",
                    "description": "Nueva API key o token Bearer (segun la accion)"
                }
            },
            "required": ["action"]
        }

    def _mask_key(self, key: str) -> str:
        if not key:
            return "No configurada"
        if len(key) <= 8:
            return "***" + key[-4:]
        return key[:4] + "..." + key[-4:]

    async def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        async with aiofiles.open(self.config_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content) if content else {}

    async def _save_config(self, config: dict):
        """Guarda config cifrando credenciales sensibles con DPAPI."""
        try:
            from cli.secure_config import save_config_secure
            save_config_secure(config, str(self.config_path))
        except ImportError:
            # Fallback si secure_config no esta disponible
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self.config_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(config, indent=4))

    async def execute(self, action: str, new_key: Optional[str] = None) -> str:
        config = await self._load_config()
        api_key = os.getenv("DEEPSEEK_API_KEY") or config.get("api_key")
        bearer_token = config.get("bearer_token")
        cookies = config.get("cookies")

        if action == "status":
            status = "**Estado de credenciales:**\n\n"
            status += f"- **Modo API key**: {self._mask_key(api_key)}\n"
            if bearer_token and cookies:
                status += f"- **Modo web**: Activo (token: {self._mask_key(bearer_token)}, cookies: {len(cookies)})\n"
            elif cookies:
                status += "- **Modo web**: Cookies capturadas, falta token Bearer. Usa `set_bearer_token`.\n"
            else:
                status += "- **Modo web**: No configurado\n"
            status += "\nUsa `instructions` para ver la guia completa."
            return status

        elif action == "set_api_key":
            if not new_key:
                return "Error: Debes proporcionar la nueva API key en 'new_key'."
            if len(new_key) < 20:
                return "Error: API key demasiado corta. Verifica que sea correcta."
            if not new_key.startswith("sk-"):
                return "Advertencia: La API key no empieza con 'sk-'. Guardada de todas formas, pero verifica que sea correcta."
            config["api_key"] = new_key
            config["bearer_token"] = None
            config["cookies"] = None
            await self._save_config(config)
            return "API key guardada."

        elif action == "test_api_key":
            if not api_key:
                return "No hay API key configurada."
            try:
                client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "Di 'funciona'"}],
                    max_tokens=10
                )
                return f"API key valida. Respuesta: {response.choices[0].message.content}"
            except Exception as e:
                return f"Error probando API key: {str(e)}"

        elif action == "web_login":
            if not PYQT_AVAILABLE:
                return "Error: PyQt5 no esta instalado. Ejecuta: pip install PyQt5 PyQtWebEngine"
            wasm_path = config.get("wasm_path", "")
            result = run_login(str(self.config_path), wasm_path=wasm_path)
            if result.get("validated"):
                return "Sesion web configurada y validada correctamente."
            elif result.get("bearer_token"):
                return f"Credenciales capturadas pero validacion fallo: {result.get('error')}"
            elif result.get("cookies"):
                return "Solo cookies capturadas. Falta bearer token — envia un mensaje en el chat de DeepSeek."
            else:
                return "No se capturaron credenciales (timeout o ventana cerrada)."

        elif action == "set_bearer_token":
            if not new_key:
                return "Error: Debes proporcionar el token Bearer en 'new_key'."
            if len(new_key) < 10:
                return "Error: Token Bearer demasiado corto. Verifica que sea correcto."
            config["bearer_token"] = new_key
            await self._save_config(config)
            return "Token Bearer guardado."

        elif action == "web_test":
            if not bearer_token or not cookies:
                return "Faltan credenciales web (token o cookies). Usa web_login primero."
            wasm_path = config.get("wasm_path", "")
            if validate_session(bearer_token, cookies, wasm_path):
                return "Sesion web valida."
            else:
                return "Sesion invalida. Ejecuta web_login para renovar."

        elif action == "web_logout":
            config["bearer_token"] = None
            config["cookies"] = None
            await self._save_config(config)
            return "Credenciales web eliminadas."

        elif action == "instructions":
            return (
                "**Guia de configuracion:**\n\n"
                "**Modo web (gratis, usa tu cuenta):**\n"
                "1. Ejecuta `web_login` para abrir chat.deepseek.com.\n"
                "2. Inicia sesion con tu cuenta.\n"
                "3. Envia un mensaje cualquiera en el chat.\n"
                "4. Cookies y token Bearer se capturan automaticamente.\n"
                "5. La sesion se valida con un test PoW y la ventana se cierra.\n"
                "6. Verifica con `web_test` cuando quieras.\n\n"
                "**Modo API key (de pago):**\n"
                "Usa `set_api_key` con tu clave de https://platform.deepseek.com/api_keys\n"
                "Verifica con `test_api_key`."
            )

        else:
            return f"Error: Accion no valida '{action}'."
