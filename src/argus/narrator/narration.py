"""Optional provider interface for prose built from an already verified report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from argus.narrator.morning import MorningReport


@dataclass(frozen=True)
class NarrationDraft:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class MorningNarrator(Protocol):
    def draft(self, report: MorningReport) -> NarrationDraft:
        """Propose wording only and return the model and token counts for logging."""
        ...
