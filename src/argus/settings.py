"""Validated operator settings shared by the API and the live runtime."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

Level = Literal["alone", "asks", "off"]
Cap = Annotated[int, Field(ge=0, le=2_000_000)]
Money = Annotated[float, Field(ge=0, le=100_000)]
Fraction = Annotated[float, Field(ge=0, le=1)]
MetricId = Annotated[str, Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True)


class AutonomySettings(Section):
    monitor: Literal["alone", "off"] = "alone"
    defer_late_data: Literal["alone", "off"] = "alone"
    investigate: Literal["alone", "off"] = "alone"
    hold_alert: Literal["alone", "off"] = "alone"
    retest_graph: Literal["alone", "off"] = "alone"
    manage_incident: Literal["alone", "off"] = "alone"
    approve_action: Literal["asks", "off"] = "asks"
    review_probation: Literal["asks", "off"] = "asks"
    review_ambiguous_cause: Literal["asks", "off"] = "asks"


class Lines(Section):
    wiggle_z: float = Field(default=2.0, gt=0, le=40)
    pair_z: float = Field(default=3.5, gt=0, le=40)
    alarm_z: float = Field(default=5.0, gt=0, le=40)

    @model_validator(mode="after")
    def in_order(self) -> Self:
        if not self.wiggle_z < self.pair_z < self.alarm_z:
            raise ValueError("Thresholds must increase from ignore to two-hour to immediate opening.")
        return self


class Thresholds(Lines):
    per_metric: dict[MetricId, Lines] = Field(default_factory=dict, max_length=100)
    supported: Fraction = 0.20
    stop: Fraction = 0.80
    plan_band: Fraction = 0.25
    plan_min: Fraction = 0.05
    freshness: Fraction = 0.999
    calm_hours: int = Field(default=3, ge=1, le=168)
    checks: int = Field(default=12, ge=1, le=100)

    @model_validator(mode="after")
    def supported_before_stop(self) -> Self:
        if self.supported > self.stop:
            raise ValueError("The supported-cause threshold must be at or below the stopping threshold.")
        return self


class Budgets(Section):
    requests: Cap = 10
    tool_calls: Cap = 12
    input_tokens: Cap = 150_000
    output_tokens: Cap = 12_000
    usd: Money = 0.50
    wall_seconds: float = Field(default=120, ge=0, le=3600)
    monthly_usd: Money | None = None


class QuietHours(Section):
    enabled: bool = False
    start: str = Field(default="22:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(default="07:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = Field(default="Europe/Berlin", max_length=96)
    weekends: bool = False
    bypass_eur: Money | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Enter an IANA timezone such as Europe/Berlin.") from None
        return value

    @model_validator(mode="after")
    def distinct_times(self) -> Self:
        if self.enabled and self.start == self.end:
            raise ValueError("Choose different start and end times.")
        return self

    def holds(self, now: datetime, severity_eur: float) -> bool:
        if self.bypass_eur is not None and abs(severity_eur) >= self.bypass_eur:
            return False
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        local = now.astimezone(ZoneInfo(self.timezone))
        if self.weekends and local.weekday() >= 5:
            return True
        start, end = time.fromisoformat(self.start), time.fromisoformat(self.end)
        clock = local.time()
        return self.enabled and (start <= clock < end if start < end else clock >= start or clock < end)


class Playbooks(Section):
    disabled: list[MetricId] = Field(default_factory=list, max_length=30)


class Channels(Section):
    in_app: bool = True
    slack: bool = False
    email: bool = False
    pagerduty: bool = False
    webhook: bool = False


Email = Annotated[str, Field(max_length=254, pattern=r"^(?:[^@\s]+@[^@\s]+\.[^@\s]+)?$")]


class Account(Section):
    name: str = Field(default="Batu", max_length=120)
    email: Email = ""


class Appearance(Section):
    theme: Literal["light", "dark"] | None = None
    language: Literal["en", "de"] = "en"


class AiModel(Section):
    provider: Literal["openai", "anthropic"] | None = None
    model: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_.:-]*$")
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and any(not 33 <= ord(c) <= 126 for c in value.get_secret_value()):
            raise ValueError("Enter a provider key without spaces or line breaks.")
        return value

    @model_validator(mode="after")
    def provider_for_key(self) -> Self:
        if (self.api_key is not None or self.model) and self.provider is None:
            raise ValueError("Select the provider for this model or key.")
        return self


class Notifications(Section):
    email: Email = ""
    slack_url: SecretStr | None = Field(default=None, max_length=2048)
    pagerduty_url: SecretStr | None = Field(default=None, max_length=2048)
    webhook_url: SecretStr | None = Field(default=None, max_length=2048)


class DataSource(Section):
    id: MetricId
    name: str = Field(min_length=1, max_length=120)
    connector: Literal["shopify", "ga4", "google-ads", "meta-ads", "stripe", "http"]
    url: str = Field(min_length=1, max_length=2048)


class DataSources(Section):
    sources: list[DataSource] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Each data source needs a unique ID.")
        return self


class Settings(Section):
    autonomy: AutonomySettings = Field(default_factory=AutonomySettings)
    playbooks: Playbooks = Field(default_factory=Playbooks)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    budgets: Budgets = Field(default_factory=Budgets)
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    channels: Channels = Field(default_factory=Channels)
    sources: DataSources = Field(default_factory=DataSources)
    ai: AiModel = Field(default_factory=AiModel)
    notifications: Notifications = Field(default_factory=Notifications)
    appearance: Appearance = Field(default_factory=Appearance)
    account: Account = Field(default_factory=Account)


def provider_settings(settings: Settings) -> tuple[str | None, str | None, str | None]:
    """Local override for ARGUS_PROVIDER, provider model, and provider key, respectively."""
    ai = settings.ai
    return ai.provider, ai.model or None, ai.api_key.get_secret_value() if ai.api_key is not None else None


def secret_fields(section: Section) -> dict[str, str | None]:
    return {
        key: value.get_secret_value() if value is not None else None
        for key, value in section
        if key == "api_key" or key in {"slack_url", "pagerduty_url", "webhook_url"}
    }


class SettingsConflict(Exception):
    """A newer write won the revision or there is no edit left to undo."""


SettingsSnapshot = tuple[int, Settings, tuple[str, ...]]


class SettingsStore:
    """Atomic settings snapshots. A pathless store belongs to one public simulator session."""

    def __init__(self, path: Path | None, defaults: Settings | None = None) -> None:
        self.path = path
        self.defaults = defaults or Settings()
        self._lock = threading.RLock()
        self._revision = 0
        self._current = self.defaults
        self._undo: dict[str, Section] = {}
        if path is not None and path.exists():
            path.chmod(0o600)
            try:
                payload = json.loads(path.read_bytes())
                self._revision = payload["revision"]
                if type(self._revision) is not int or self._revision < 0:
                    raise ValueError
                self._current = Settings.model_validate(payload["settings"])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("The local Argus settings file is invalid.") from None

    def read(self) -> Settings:
        with self._lock:
            return self._current

    def snapshot(self) -> SettingsSnapshot:
        with self._lock:
            return self._revision, self._current, tuple(self._undo)

    def update(
        self, area: str, revision: int, change: Callable[[Section], Section], *, undo: bool = False
    ) -> SettingsSnapshot:
        with self._lock:
            if revision != self._revision:
                raise SettingsConflict
            current = getattr(self._current, area)
            if undo:
                previous = self._undo.get(area)
                if previous is None:
                    raise SettingsConflict
                updated = previous
            else:
                updated = change(current)
            self._commit(self._current.model_copy(update={area: updated}))
            self._undo.pop(area, None)
            if not undo:
                self._undo[area] = current
            return self.snapshot()

    def reset(self, revision: int) -> SettingsSnapshot:
        with self._lock:
            if revision != self._revision:
                raise SettingsConflict
            self._commit(self.defaults)
            self._undo.clear()
            return self.snapshot()

    def _commit(self, settings: Settings) -> None:
        if self.path is not None:
            payload = settings.model_dump(mode="json")
            for key, section in settings:
                payload[key].update(secret_fields(section))
            write_private_json(self.path, {"revision": self._revision + 1, "settings": payload})
        self._current = settings
        self._revision += 1


def write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".argus-settings-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(payload, output, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
