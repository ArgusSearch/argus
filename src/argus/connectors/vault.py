"""Persist connector credentials outside the project, with private atomic writes."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, SecretStr

from argus.connectors.provider import ProviderId

SERVICE = "dev.argussearch.argus"
NONCE_SIZE = 12


class Keyring(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class CredentialStorageError(RuntimeError):
    """The OS keyring failed without exposing backend details."""


class Credentials(BaseModel):
    key: SecretStr
    target: str


def atomic_write(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            file.close()
            if exclusive:
                os.link(temp, path)
            else:
                os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


class Vault:
    def __init__(self, directory: Path, keyring: Keyring | None = None) -> None:
        self.directory = directory
        self.keyring = keyring

    @contextmanager
    def _native(self) -> Iterator[Keyring]:
        assert self.keyring is not None
        try:
            yield self.keyring
        except Exception:
            raise CredentialStorageError from None

    def _cipher(self, *, create: bool = False) -> AESGCM:
        path = self.directory / "master.key"
        if create and not path.exists():
            with suppress(FileExistsError):
                atomic_write(path, AESGCM.generate_key(bit_length=256), exclusive=True)
        return AESGCM(path.read_bytes())

    def _path(self, provider: ProviderId) -> Path:
        return self.directory / f"{provider}.enc"

    @staticmethod
    def _account(provider: ProviderId) -> str:
        return f"connection-{provider}"

    def read(self, provider: ProviderId) -> Credentials | None:
        if self.keyring:
            with self._native() as store:
                value = store.get_password(SERVICE, self._account(provider))
            return Credentials.model_validate_json(value) if value is not None else None
        try:
            payload = self._path(provider).read_bytes()
        except FileNotFoundError:
            return None
        plain = self._cipher().decrypt(payload[:NONCE_SIZE], payload[NONCE_SIZE:], provider.encode())
        return Credentials.model_validate_json(plain)

    def save(self, provider: ProviderId, credentials: Credentials) -> None:
        value = json.dumps({"key": credentials.key.get_secret_value(), "target": credentials.target})
        if self.keyring:
            with self._native() as store:
                store.set_password(SERVICE, self._account(provider), value)
        else:
            nonce = secrets.token_bytes(NONCE_SIZE)
            data = self._cipher(create=True).encrypt(nonce, value.encode(), provider.encode())
            atomic_write(self._path(provider), nonce + data)

    def delete(self, provider: ProviderId) -> None:
        if self.keyring:
            account = self._account(provider)
            with self._native() as store:
                if store.get_password(SERVICE, account) is not None:
                    store.delete_password(SERVICE, account)
        else:
            self._path(provider).unlink(missing_ok=True)
