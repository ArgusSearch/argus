"""The hard boundary in code: every number the agent writes must come from a receipted tool result.

`FactBook` collects numbers by the receipts of the tool results they came from. `check` reads a draft
sentence by sentence: each measured number must match a value from a receipt cited in that sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
TAGS = r"[aqr]\d+(?:\s*,\s*[aqr]\d+)*"
TAG = re.compile(rf"\[({TAGS})\]")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+")
# Not quantities: receipt tags and ids, inline code, incident/anomaly/action ids, dates and clock times,
# list markers, model and version names.
NON_QUANTITIES = (
    rf"\[{TAGS}\]|\b[aqr]\d+\b|INC-\d+|\ban_p?\d+\b|\b(?:act|rep|run|h)_?\d+\b"
    r"|\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\b\d{1,2}:\d{2}\b"
    r"|\b\d+\.\d+\.\d+\b|\b[A-Za-z]+[-_]\d[\w.\-]*|\b(?:[Vv]ersion|pacer|v)\s*\d+(?:\.\d+)+"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b"
    r"|\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}\b"
)
CHECK_SKIP = re.compile(NON_QUANTITIES)
SKIP = re.compile(NON_QUANTITIES + r"|`[^`]*`|^\s*\d+\.\s|^#+.*$")


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
    by_receipt: dict[str, set[float]] = field(default_factory=dict)

    def add(self, result: Any, receipts: list[str]) -> None:
        """Record a tool result. A result without receipts adds no numbers: nothing backs them."""
        if not receipts:
            return
        values: set[float] = set()
        numbers_in(result, values)
        self.values.update(values)
        for receipt in receipts:
            self.by_receipt.setdefault(receipt, set()).update(values)

    def backs(self, token: str, tags: list[str] | None = None, *, percent: bool = True) -> bool:
        x = float(token.replace(",", ""))
        decimals = len(token.split(".")[1]) if "." in token else 0
        tol = 0.5 * 10**-decimals + 1e-9
        signed = token[0] in "+-"
        values = self.values if not tags else {v for tag in tags for v in self.by_receipt.get(tag, ())}
        candidates = values | {v * 100 for v in values} if percent else values
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
            parts.append(f"numbers without matching receipt values: {', '.join(self.unbacked[:12])}")
        if self.untagged:
            parts.append(
                "sentences with numbers but no [receipt] tag: " + " | ".join(s[:80] for s in self.untagged[:5])
            )
        if self.unknown_receipts:
            parts.append(f"receipt tags this run never saw: {', '.join(self.unknown_receipts[:12])}")
        return "; ".join(parts)


SENTENCE = re.compile(r"(?<=[.!?:;])\s+(?=\S)")
LEADING_TAGS = re.compile(rf"^((?:\s*\[{TAGS}\])+)")
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
        for sentence in sentences(LIST_MARKER.sub("", line)):
            tags = [t.strip() for group in TAG.findall(sentence) for t in group.split(",")]
            cited.extend(t for t in tags if t not in cited)
            unknown.extend(t for t in tags if t not in facts.by_receipt and t not in unknown)
            quantities = CHECK_SKIP.sub(" ", sentence)
            tokens = list(NUMBER.finditer(quantities))
            for token in tokens:
                suffix = quantities[token.end() :].lstrip()
                if not facts.backs(token.group(), tags, percent=suffix.startswith("%")):
                    unbacked.append(token.group())
            if tokens and not tags:
                untagged.append(sentence.strip())
    return NumberCheck(unbacked, untagged, unknown, cited)


UNVERIFIED = "[unverified]"
ANSWER_NUMBER = re.compile(r"[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?")


def scrub_answer(text: str) -> str:
    """Ask prose takes no figures; only verified claims supply the rendered digits."""
    return ANSWER_NUMBER.sub(UNVERIFIED, text)


def scrub(text: str, facts: FactBook) -> str:
    """Model-written text for the activity log: every number no receipted result of the run backs is replaced
    by UNVERIFIED, so the log only carries numbers that passed verification."""
    skipped = [m.span() for m in SKIP.finditer(text)]
    out, last = [], 0
    for m in NUMBER.finditer(text):
        start, end = m.span()
        if any(a <= start < b or a < end <= b for a, b in skipped) or _structural(m.group()) or facts.backs(m.group()):
            continue
        out += [text[last:start], UNVERIFIED]
        last = end
    out.append(text[last:])
    return "".join(out)


def _structural(token: str) -> bool:
    x = float(token.replace(",", ""))
    return token[0] not in "+-" and "." not in token and abs(x) <= 10
