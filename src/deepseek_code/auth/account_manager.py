"""Gestor de multiples cuentas DeepSeek.

Permite guardar, listar, cambiar y eliminar cuentas (perfiles)
que se almacenan en accounts.json dentro de APPDATA.
Las credenciales se cifran con DPAPI (Windows).
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

ACCOUNTS_FILE = "accounts.json"

# Campos de credenciales que se copian entre cuentas
CREDENTIAL_FIELDS = ("bearer_token", "cookies", "api_key", "wasm_path")


class AccountManager:
    """Gestiona multiples cuentas DeepSeek con persistencia en JSON."""

    def __init__(self, appdata_dir: str):
        self.appdata_dir = appdata_dir
        self._accounts_path = os.path.join(appdata_dir, ACCOUNTS_FILE)

    def _load_store(self) -> dict:
        """Carga el store de cuentas desde disco."""
        if not os.path.exists(self._accounts_path):
            return {"active": None, "accounts": {}}
        try:
            with open(self._accounts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "accounts" not in data:
                data["accounts"] = {}
            return data
        except (json.JSONDecodeError, IOError):
            return {"active": None, "accounts": {}}

    def _save_store(self, store: dict):
        """Guarda el store de cuentas a disco con DPAPI."""
        os.makedirs(self.appdata_dir, exist_ok=True)

        # Cifrar credenciales sensibles antes de guardar
        try:
            from cli.secure_config import encrypt_value, _dpapi_available, SENSITIVE_FIELDS
            use_dpapi = _dpapi_available()
        except ImportError:
            use_dpapi = False
            SENSITIVE_FIELDS = set()

        output = {"active": store.get("active"), "accounts": {}}
        for name, account in store.get("accounts", {}).items():
            encrypted_account = {}
            for k, v in account.items():
                if use_dpapi and k in SENSITIVE_FIELDS and v is not None:
                    encrypted_account[k] = encrypt_value(v)
                else:
                    encrypted_account[k] = v
            output["accounts"][name] = encrypted_account

        with open(self._accounts_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

    def _decrypt_account(self, account: dict) -> dict:
        """Descifra credenciales de una cuenta."""
        try:
            from cli.secure_config import decrypt_value
        except ImportError:
            return account

        decrypted = {}
        for k, v in account.items():
            if isinstance(v, str) and v.startswith("DPAPI:"):
                try:
                    decrypted[k] = decrypt_value(v)
                except Exception:
                    decrypted[k] = None
            else:
                decrypted[k] = v
        return decrypted

    def list_accounts(self) -> list:
        """Lista cuentas guardadas.

        Returns:
            Lista de dicts: [{name, mode, last_used, is_active}]
        """
        store = self._load_store()
        active = store.get("active")
        result = []
        for name, account in store.get("accounts", {}).items():
            result.append({
                "name": name,
                "mode": account.get("mode", "unknown"),
                "last_used": account.get("last_used"),
                "created_at": account.get("created_at"),
                "is_active": name == active,
            })
        # Ordenar: activa primero, luego por last_used
        result.sort(key=lambda x: (not x["is_active"], x.get("last_used") or ""))
        return result

    def add_account(self, name: str, config_data: dict):
        """Guarda una cuenta con nombre descriptivo.

        Args:
            name: Nombre unico para la cuenta (ej: "personal-web", "work-api")
            config_data: Dict con credenciales (bearer_token, cookies, api_key, etc)
        """
        store = self._load_store()
        now = datetime.now(timezone.utc).isoformat()

        # Detectar modo
        mode = "unknown"
        if config_data.get("bearer_token") and config_data.get("cookies"):
            mode = "web"
        elif config_data.get("api_key"):
            mode = "api"

        account = {
            "mode": mode,
            "created_at": now,
            "last_used": now,
        }
        # Copiar solo campos de credenciales
        for field in CREDENTIAL_FIELDS:
            if field in config_data and config_data[field] is not None:
                account[field] = config_data[field]

        store["accounts"][name] = account
        # Si es la primera cuenta, hacerla activa
        if store.get("active") is None:
            store["active"] = name

        self._save_store(store)

    def switch_account(self, name: str) -> Optional[dict]:
        """Cambia a otra cuenta y retorna sus credenciales descifradas.

        Args:
            name: Nombre de la cuenta a activar

        Returns:
            Dict con credenciales descifradas, o None si no existe
        """
        store = self._load_store()
        if name not in store.get("accounts", {}):
            return None

        # Actualizar last_used de la cuenta destino
        now = datetime.now(timezone.utc).isoformat()
        store["accounts"][name]["last_used"] = now
        store["active"] = name
        self._save_store(store)

        # Retornar credenciales descifradas
        return self._decrypt_account(store["accounts"][name])

    def remove_account(self, name: str) -> bool:
        """Elimina una cuenta guardada.

        Args:
            name: Nombre de la cuenta a eliminar

        Returns:
            True si se elimino, False si no existia
        """
        store = self._load_store()
        if name not in store.get("accounts", {}):
            return False

        del store["accounts"][name]

        # Si era la activa, limpiar
        if store.get("active") == name:
            remaining = list(store["accounts"].keys())
            store["active"] = remaining[0] if remaining else None

        self._save_store(store)
        return True

    def get_active_account(self) -> Optional[str]:
        """Retorna el nombre de la cuenta activa."""
        store = self._load_store()
        return store.get("active")

    def save_current_as(self, name: str, config: dict):
        """Atajo: guarda la config actual como una cuenta nombrada."""
        self.add_account(name, config)
