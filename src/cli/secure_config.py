"""Almacenamiento seguro de credenciales usando Windows DPAPI.

Las credenciales sensibles (bearer_token, cookies, api_key) se cifran
con DPAPI (Data Protection API) del usuario actual de Windows.
Solo el mismo usuario en la misma maquina puede descifrarlas.

Si DPAPI no esta disponible (Linux, error), se usa el modo
plaintext con un warning al usuario.
"""

import json
import os
import base64
import sys
from typing import Optional

# Campos que contienen credenciales sensibles
SENSITIVE_FIELDS = {"bearer_token", "cookies", "api_key"}
ENCRYPTED_SUFFIX = ".enc"


def _dpapi_available() -> bool:
    """Verifica si Windows DPAPI esta disponible."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes
        crypt32 = ctypes.windll.crypt32
        return hasattr(crypt32, "CryptProtectData")
    except Exception:
        return False


def _dpapi_encrypt(data: bytes) -> bytes:
    """Cifra datos usando Windows DPAPI (CryptProtectData)."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char))
        ]

    input_blob = DATA_BLOB()
    input_blob.cbData = len(data)
    input_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(data, len(data)),
        ctypes.POINTER(ctypes.c_char)
    )
    output_blob = DATA_BLOB()

    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),   # pDataIn
        None,                        # szDataDescr
        None,                        # pOptionalEntropy
        None,                        # pvReserved
        None,                        # pPromptStruct
        0x01,                        # dwFlags = CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(output_blob)   # pDataOut
    )

    if not result:
        raise OSError("DPAPI CryptProtectData fallo")

    encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return encrypted


def _dpapi_decrypt(data: bytes) -> bytes:
    """Descifra datos usando Windows DPAPI (CryptUnprotectData)."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char))
        ]

    input_blob = DATA_BLOB()
    input_blob.cbData = len(data)
    input_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(data, len(data)),
        ctypes.POINTER(ctypes.c_char)
    )
    output_blob = DATA_BLOB()

    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None, None, None, None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(output_blob)
    )

    if not result:
        raise OSError("DPAPI CryptUnprotectData fallo (token de otro usuario?)")

    decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return decrypted


def encrypt_value(value) -> str:
    """Cifra un valor sensible y retorna string base64 con prefijo."""
    if value is None:
        return None
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    encrypted = _dpapi_encrypt(raw)
    return "DPAPI:" + base64.b64encode(encrypted).decode("ascii")


def decrypt_value(value: str):
    """Descifra un valor con prefijo DPAPI:, retorna el valor original."""
    if not isinstance(value, str) or not value.startswith("DPAPI:"):
        return value  # No cifrado, retornar tal cual
    encrypted = base64.b64decode(value[6:])
    decrypted = _dpapi_decrypt(encrypted)
    return json.loads(decrypted.decode("utf-8"))


def save_config_secure(config: dict, config_path: str):
    """Guarda config cifrando campos sensibles con DPAPI."""
    output = {}
    use_dpapi = _dpapi_available()

    for key, value in config.items():
        if key.startswith("_"):
            continue  # No guardar campos internos (_config_path)
        if use_dpapi and key in SENSITIVE_FIELDS and value is not None:
            output[key] = encrypt_value(value)
        else:
            output[key] = value

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


def load_config_secure(config_path: str) -> dict:
    """Carga config descifrando campos sensibles con DPAPI."""
    if not os.path.exists(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    config = {}
    for key, value in raw.items():
        if isinstance(value, str) and value.startswith("DPAPI:"):
            try:
                config[key] = decrypt_value(value)
            except Exception:
                # No se pudo descifrar (otro usuario/maquina)
                config[key] = None
        else:
            config[key] = value

    return config


def mask_token(token: str, visible: int = 4) -> str:
    """Enmascara un token mostrando solo los primeros/ultimos chars."""
    if not token or len(token) < visible * 2:
        return "***"
    return token[:visible] + "..." + token[-visible:]
