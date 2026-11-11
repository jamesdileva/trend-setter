"""Secret storage abstraction (implementation.md §12).

Secrets never live in SQLite, config files, logs, or the local API. The
Windows implementation uses Windows Credential Manager through ``keyring``
(ADR-0002); the in-memory implementation serves tests and non-Windows
development only. The Windows backend is imported lazily so Linux
environments never load it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

SERVICE_NAME = "trend-setter"


class SecretStore(ABC):
    """Platform-neutral credential storage interface."""

    @abstractmethod
    def set_secret(self, key: str, value: str) -> None:
        """Store or replace one secret under ``key``."""

    @abstractmethod
    def get_secret(self, key: str) -> str | None:
        """Return the secret for ``key``, or None when absent."""

    @abstractmethod
    def delete_secret(self, key: str) -> bool:
        """Delete the secret for ``key``. Returns True when it existed."""


class InMemorySecretStore(SecretStore):
    """Non-durable store for tests and non-Windows development only."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def set_secret(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def get_secret(self, key: str) -> str | None:
        return self._secrets.get(key)

    def delete_secret(self, key: str) -> bool:
        return self._secrets.pop(key, None) is not None


class WindowsCredentialManagerSecretStore(SecretStore):
    """Windows Credential Manager storage (user scope, ADR-0002).

    Do not instantiate in automated tests: it would touch the real,
    logged-in user's credential store.
    """

    def set_secret(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(SERVICE_NAME, key, value)

    def get_secret(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE_NAME, key)

    def delete_secret(self, key: str) -> bool:
        import keyring

        if keyring.get_password(SERVICE_NAME, key) is None:
            return False
        keyring.delete_password(SERVICE_NAME, key)
        return True


def default_secret_store() -> SecretStore:
    """Pick the platform-appropriate store (Windows only gets Credential Manager)."""
    import sys

    if sys.platform == "win32":
        return WindowsCredentialManagerSecretStore()
    return InMemorySecretStore()
