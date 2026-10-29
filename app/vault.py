"""Cifrado en reposo de secretos (contraseñas de OLT, comunidades SNMP, claves privadas de VPN)."""
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.secret_key.strip()
    if not key:
        path = Path(settings.secret_key_file)
        if path.exists():
            key = path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            # Se crea con permisos 600 desde el inicio (sin ventana donde sea legible por otros)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(key)
    return Fernet(key.encode())


class VaultError(Exception):
    """No se pudo descifrar un secreto guardado."""


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise VaultError("No se pudo descifrar un secreto: ¿cambió la clave ONU_SECRET_KEY / secret.key?") from exc
