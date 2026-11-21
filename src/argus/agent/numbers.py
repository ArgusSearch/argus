"""The hard boundary in code: every number the agent writes must come from a receipted tool result.

`FactBook` collects every number of every tool result the agent saw in one run, each with the receipts of
the result it came from. `check` reads a draft report sentence by sentence: a number that matches no fact is
unbacked, and a line with a number but no `[receipt]` tag naming a receipt the run actually saw is
untagged. A report with either, or with a citation that is not a receipt id, is returned to the model to fix; it is
never filed. Tags are checked per sentence, so one tag at the end of a paragraph cannot vouch for it all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
TAG = re.compile(r"\[((?:[ra]\d+)(?:\s*,\s*[ra]\d+)*)\]")
# Not quantities: receipt tags and ids, inline code, incident/anomaly/action ids, dates and clock times,
# list markers, model and version names.
SKIP = re.compile(
    r"\[[ra]\d+(?:\s*,\s*[ra]\d+)*\]|\b[ra]\d+\b|`[^`]*`|INC-\d+|\ban_p?\d+\b|\b(?:act|rep|run|h)_?\d+\b"
    r"|\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\b\d{1,2}:\d{2}\b|^\s*\d+\.\s|^#+.*$"
    r"|\b\d+\.\d+\.\d+\b|\b[A-Za-z]+[-_]\d[\w.\-]*|\b(?:[Vv]ersion|pacer|v)\s*\d+(?:\.\d+)+"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b"
    r"|\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}\b"
)


def numbers_in(value: Any, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        out.add(float(value))
    elif isinstance(value, str):
        for m in NUMBER.findall(SKIP.sub(" ", value)):
            out.add(float(m.replace(",", "")))
    elif isinstance(value, dict):
        for v in value.values():
            numbers_in(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            numbers_in(v, out)


@dataclass
class FactBook:
    """Numbers the run has seen, from receipted tool results only."""

    values: set[float] = field(default_factory=set)
    receipts: set[str] = field(default_factory=set)

    def add(self, result: Any, receipts: list[str]) -> None:
        """Record a tool result. A result without receipts adds no numbers: nothing backs them."""
        if not receipts:
            return
        self.receipts.update(receipts)
        numbers_in(result, self.values)

    def backs(self, token: str) -> bool:
        x = float(token.replace(",", ""))
        decimals = len(token.split(".")[1]) if "." in token else 0
        tol = 0.5 * 10**-decimals + 1e-9
        signed = token[0] in "+-"
        if not signed and abs(x) <= 10 and decimals == 0 and x == int(x):
            return True  # small counts in prose ("two checks", "3 hours") are structure, not measurements
        candidates = self.values | {v * 100 for v in self.values}
        return any(abs((x if signed else abs(x)) - (v if signed else abs(v))) <= tol for v in candidates)


@dataclass(frozen=True)
class NumberCheck:
    unbacked: list[str]
    untagged: list[str]
    unknown_receipts: list[str]
    cited: list[str]

    @property
    def ok(self) -> bool:
        return not (self.unbacked or self.untagged or self.unknown_receipts)

    def problems(self) -> str:
        parts = []
        if self.unbacked:
            parts.append(f"numbers no tool result of this run backs: {', '.join(self.unbacked[:12])}")
        if self.untagged:
            parts.append(
                "sentences with numbers but no [receipt] tag: " + " | ".join(s[:80] for s in self.untagged[:5])
            )
        if self.unknown_receipts:
            parts.append(f"receipt tags this run never saw: {', '.join(self.unknown_receipts[:12])}")
        return "; ".join(parts)


SENTENCE = re.compile(r"(?<=[.!?:;])\s+(?=\S)")
LEADING_TAGS = re.compile(r"^((?:\s*\[[ra]\d+(?:\s*,\s*[ra]\d+)*\])+)")
PSEUDO = re.compile(r"\[[^\]]*(?:INC-\d|\b(?:get|list|check)_\w+)[^\]]*\]")


def sentences(line: str) -> list[str]:
    """Split a line into sentences; a receipt tag that opens a sentence belongs to the one before it."""
    out: list[str] = []
    for piece in SENTENCE.split(line):
        lead = LEADING_TAGS.match(piece)
        if lead and out:
            out[-1] += " " + lead.group(1).strip()
            piece = piece[lead.end() :]
        if piece.strip():
            out.append(piece)
    return out


def check(report: str, facts: FactBook) -> NumberCheck:
    """Per sentence: every number backed by a fact, every sentence with a measured number tagged."""
    unbacked: list[str] = []
    untagged: list[str] = []
    unknown: list[str] = []
    cited: list[str] = []
    for line in report.splitlines():
        unknown.extend(f"{p} (cite receipt ids like [a12])" for p in PSEUDO.findall(line) if p not in unknown)
        for sentence in sentences(line):
            tags = [t.strip() for group in TAG.findall(sentence) for t in group.split(",")]
            cited.extend(t for t in tags if t not in cited)
            unknown.extend(t for t in tags if t not in facts.receipts and t not in unknown)
            tokens = NUMBER.findall(SKIP.sub(" ", sentence))
            unbacked.extend(t for t in tokens if not facts.backs(t))
            if any(not _structural(t) for t in tokens) and not tags:
                untagged.append(sentence.strip())
    return NumberCheck(unbacked, untagged, unknown, cited)


UNVERIFIED = "[unverified]"


def scrub(text: str, facts: FactBook) -> str:
    """Model-written text for the activity log: every number no receipted result of the run backs is replaced
    by UNVERIFIED, so the log only carries numbers that passed verification."""
    skipped = [m.span() for m in SKIP.finditer(text)]
    out, last = [], 0
    for m in NUMBER.finditer(text):
        start, end = m.span()
        if any(a <= start < b or a < end <= b for a, b in skipped) or facts.backs(m.group()):
            continue
        out += [text[last:start], UNVERIFIED]
        last = end
    out.append(text[last:])
    return "".join(out)


def _structural(token: str) -> bool:
    x = float(token.replace(",", ""))
    return token[0] not in "+-" and "." not in token and abs(x) <= 10
