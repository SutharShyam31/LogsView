from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

KEY_PATH = Path.home() / ".secrets" / "logsview.key"


def _load_or_create_key() -> bytes:
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        KEY_PATH.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    return key


def encrypt(plaintext: str) -> str:
    return Fernet(_load_or_create_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return Fernet(_load_or_create_key()).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return token
