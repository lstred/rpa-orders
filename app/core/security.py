"""Secret management. API keys are stored in the OS-native secret vault
(Windows Credential Manager) via keyring — never in source, config, or the DB."""
from __future__ import annotations

import keyring

SERVICE_NAME = "OrdersRpaBridge"


def set_secret(name: str, value: str) -> None:
    """Store a secret (e.g. an AI provider API key) in the OS vault."""
    keyring.set_password(SERVICE_NAME, name, value)


def get_secret(name: str) -> str | None:
    """Retrieve a secret from the OS vault, or None if not set."""
    try:
        return keyring.get_password(SERVICE_NAME, name)
    except Exception:
        return None


def delete_secret(name: str) -> None:
    """Remove a secret from the OS vault."""
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass


def has_secret(name: str) -> bool:
    return bool(get_secret(name))
