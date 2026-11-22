"""Manage one local connection per provider and publish successful syncs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

import duckdb
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, ValidationError

from argus.connectors import plausible, stripe
from argus.connectors.data import Snapshot, SourceData
from argus.connectors.provider import PROVIDERS, Fetch, ProviderError, ProviderId, request
from argus.connectors.vault import Credentials, Vault

STORAGE_ERROR = "Local credential storage is unavailable."
IMPORT_ERROR = "The provider responded, but Argus could not import its metrics."
STATE_ERRORS = (OSError, InvalidTag, ValidationError, RuntimeError)


class Status(BaseModel):
    id: ProviderId
    status: Literal["connected", "missing", "error"]
    has_key: bool
    last_synced: datetime | None = None
    error: str | None = None
    target: str | None = None


class ConnectionBusy(RuntimeError):
    pass


class Connections:
    def __init__(
        self,
        vault: Vault,
        data: SourceData,
        publish: Callable[[Snapshot], None] | None,
        *,
        fetch: Fetch = request,
    ) -> None:
        self.vault = vault
        self.data = data
        self.publish = publish
        self.fetch = fetch
        self._errors: dict[ProviderId, str] = {}
        self._locks = {provider: Lock() for provider in PROVIDERS}

    def restore(self) -> None:
        """Rebuild the live graph from saved reports, even after a key was removed."""
        if self.publish is None:
            return
        for provider in PROVIDERS:
            try:
                if snapshot := self.data.latest(provider):
                    self.publish(snapshot)
            except (OSError, duckdb.Error, ValueError, RuntimeError):
                self._errors[provider] = IMPORT_ERROR

    def status(self, provider: ProviderId) -> Status:
        try:
            credentials = self.vault.read(provider)
        except STATE_ERRORS:
            return Status(id=provider, status="error", has_key=False, error=STORAGE_ERROR)
        error = self._errors.get(provider)
        snapshot = self.data.latest(provider) if credentials else None
        return Status(
            id=provider,
            status="error" if error else "connected" if credentials else "missing",
            has_key=credentials is not None,
            target=credentials.target if credentials else None,
            last_synced=snapshot.synced_at.replace(tzinfo=UTC) if snapshot else None,
            error=error,
        )

    def sync(self, provider: ProviderId, new: Credentials | None = None) -> Status:
        lock = self._locks[provider]
        if not lock.acquire(blocking=False):
            raise ConnectionBusy
        try:
            previous = self.vault.read(provider)
            credentials = new or previous
            if credentials is None:
                raise ProviderError("Paste an API key to test the connection.")
            key = credentials.key.get_secret_value()
            if provider == "plausible":
                report = plausible.sync(self.fetch, key, credentials.target)
            else:
                report = stripe.sync(self.fetch, key, credentials.target, datetime.now(UTC).date())
            snapshot = self.data.store(provider, report, credentials.target if provider == "stripe" else None)
            try:
                if new:
                    self.vault.save(provider, new)
                if self.publish is not None:
                    self.publish(snapshot)
            except (ValueError, duckdb.Error, *STATE_ERRORS):
                snapshot.path.unlink(missing_ok=True)
                if new:
                    if previous is not None:
                        self.vault.save(provider, previous)
                    else:
                        self.vault.delete(provider)
                raise
        except ProviderError as exc:
            self._errors[provider] = str(exc)
        except STATE_ERRORS:
            self._errors[provider] = STORAGE_ERROR
        except (ValueError, duckdb.Error):
            self._errors[provider] = IMPORT_ERROR
        else:
            self._errors.pop(provider, None)
        finally:
            lock.release()
        return self.status(provider)

    def disconnect(self, provider: ProviderId) -> Status:
        lock = self._locks[provider]
        if not lock.acquire(blocking=False):
            raise ConnectionBusy
        try:
            self.vault.delete(provider)
        except STATE_ERRORS:
            self._errors[provider] = STORAGE_ERROR
        else:
            self._errors.pop(provider, None)
        finally:
            lock.release()
        return self.status(provider)
