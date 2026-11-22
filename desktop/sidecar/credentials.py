"""Store the desktop provider key using the platform's native credential store."""

import sys

from keyring.backend import KeyringBackend

SERVICE = "dev.argussearch.argus"
ACCOUNT = "anthropic-api-key"


def backend() -> KeyringBackend:
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    raise RuntimeError("Desktop credentials are supported on macOS and Windows")


def get_key() -> str | None:
    return backend().get_password(SERVICE, ACCOUNT)


def update_key(key: str | None) -> None:
    store = backend()
    if key is not None:
        if not key or len(key) > 512 or any(not char.isascii() or char.isspace() for char in key):
            raise ValueError("Invalid API key")
        store.set_password(SERVICE, ACCOUNT, key)
    elif store.get_password(SERVICE, ACCOUNT) is not None:
        store.delete_password(SERVICE, ACCOUNT)
