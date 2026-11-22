"""Declared hypotheses (profile v2, feature `hypotheses`): the detective names its rivals before it tests.

Before its first causal check the v2 detective calls `propose_hypotheses` with two to five competing
explanations, each with the cheapest check that could decide it (the Tree-of-Thoughts pattern of several
candidate branches under a budget, Yao et al. 2023, arXiv 2305.10601, implemented fresh). Every later
check names the card it tests (`hypothesis_id`).

The model never moves a card. The host's `HypothesisBook` moves cards only on judged outcomes, with the
same table the derived board uses (`argus.agent.board`):

| kind        | decisive tools                      | supported on            | ruled out on          |
|-------------|-------------------------------------|-------------------------|-----------------------|
| `event`     | holdout_check                       | consistent              | refuted               |
| `data`      | check_freshness, check_identities   | incomplete, broken      | complete, hold        |
| `market`    | market_control                      | market                  | us                    |
| `mix`       | mix_rate_split                      | mix                     | rate                  |
| `recurring` | placebo_test                        | recurring               | unusual               |
| `segment`   | segment_search                      | localized               | diffuse               |

A check of a tool that cannot decide the card's kind is attached to the card without moving it. At the
end of the run the book settles on what the gate admitted (including the checks it backfilled) and marks
every card that is still open `not_tested`, so no card stays open after `run_finished`.

Activity (kind `hypothesis`): one line with `args = {"declared": [DeclaredHypothesis]}` and one line per
move with `args = {"move": HypothesisMove}`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, get_args

from pydantic import ValidationError

from argus.agent.types import DeclaredHypothesis, HypothesisKind, HypothesisMove, HypothesisStatus
from argus.contracts.findings import EvidenceRef, RuledOut

PROPOSE = "propose_hypotheses"
MIN_CARDS, MAX_CARDS = 2, 5
CARD_ID = re.compile(r"^H[1-5]$")
DIGIT = re.compile(r"\d")

# static cost of one check (cheapest decisive check), and the tools that can flip a card of each kind
COST: dict[str, int] = {
    "list_events": 1,
    "market_control": 1,
    "placebo_test": 1,
    "holdout_check": 1,
    "get_series": 1,
    "check_freshness": 1,
    "check_identities": 1,
    "sql_check": 2,
    "segment_search": 2,
    "decompose_formula": 2,
    "mix_rate_split": 2,
    "counterfactual_impact": 3,
}
DECISIVE: dict[str, dict[str, tuple[str, ...]]] = {
    "event": {"holdout_check": ("consistent", "refuted")},
    "data": {"check_freshness": ("incomplete", "complete"), "check_identities": ("broken", "hold")},
    "market": {"market_control": ("market", "us")},
    "mix": {"mix_rate_split": ("mix", "rate")},
    "recurring": {"placebo_test": ("recurring", "unusual")},
    "segment": {"segment_search": ("localized", "diffuse")},
}
"""kind -> tool -> (outcome that supports the card, outcome that rules it out)."""


def propose_spec() -> dict[str, Any]:
    card = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "'H1' to 'H5', unique"},
            "statement": {"type": "string", "description": "what would be true; words only, no digits"},
            "kind": {"type": "string", "enum": list(get_args(HypothesisKind))},
            "event_ref": {"type": "string", "description": "ref of the logged event, for kind 'event'"},
            "parent": {"type": "string", "description": "id of the hypothesis this one refines, if any"},
            "decisive_check": {"type": "string", "enum": sorted(COST)},
            "why_cheapest": {"type": "string", "description": "one short sentence, no numbers"},
        },
        "required": ["id", "statement", "kind", "decisive_check", "why_cheapest"],
        "additionalProperties": False,
    }
    return {
        "name": PROPOSE,
        "description": "Declare two to five competing hypotheses before the first causal check, each with the "
        "single cheapest check that could decide it. Code moves the cards only on judged checks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hypotheses": {"type": "array", "items": card, "minItems": MIN_CARDS, "maxItems": MAX_CARDS}
            },
            "required": ["hypotheses"],
            "additionalProperties": False,
        },
    }


def hypothesis_id_property() -> dict[str, Any]:
    return {"type": "string", "description": "id of the declared hypothesis this check tests ('H1', ...)"}


class Declined(ValueError):
    """A declaration the host refuses; the message goes back to the model as the repair."""


@dataclass
class Card:
    declared: DeclaredHypothesis
    status: HypothesisStatus = "open"
    reason: str = "declared, not yet tested"
    checks: list[str] = field(default_factory=list)  # call ids attached to the card
    first_tool: str | None = None

    @property
    def id(self) -> str:
        return self.declared.id


def parse(raw: dict[str, Any]) -> list[DeclaredHypothesis]:
    items = raw.get("hypotheses")
    if not isinstance(items, list) or not MIN_CARDS <= len(items) <= MAX_CARDS:
        raise Declined(f"declare {MIN_CARDS} to {MAX_CARDS} competing hypotheses")
    cards: list[DeclaredHypothesis] = []
    for item in items:
        try:
            card = DeclaredHypothesis.model_validate(item)
        except ValidationError as exc:
            raise Declined(f"invalid hypothesis: {exc.errors()[0].get('msg', 'invalid')}") from exc
        if not CARD_ID.fullmatch(card.id):
            raise Declined(f"hypothesis ids are 'H1' to 'H5', not {card.id!r}")
        if DIGIT.search(card.statement) or DIGIT.search(card.why_cheapest):
            raise Declined(f"{card.id}: write the statement and why_cheapest in words, without digits")
        if card.decisive_check not in COST:
            raise Declined(f"{card.id}: decisive_check must be one of {sorted(COST)}")
        decisive = DECISIVE.get(card.kind)
        if decisive:
            lowest = min(COST[tool] for tool in decisive)
            cheapest = [tool for tool in decisive if COST[tool] == lowest]
            if card.decisive_check not in cheapest:
                raise Declined(f"{card.id}: cheapest decisive_check for {card.kind} must be one of {cheapest}")
        cards.append(card)
    ids = [c.id for c in cards]
    if len(set(ids)) != len(ids):
        raise Declined("hypothesis ids must be unique")
    by_id = {c.id: c for c in cards}
    for c in cards:
        if c.parent is None:
            continue
        parent = by_id.get(c.parent)
        if parent is None or parent.id == c.id:
            raise Declined(f"{c.id}: parent {c.parent!r} is not another declared hypothesis")
        if parent.parent is not None:
            raise Declined(f"{c.id}: refine a top-level hypothesis (the tree is at most two levels deep)")
    return cards


class HypothesisBook:
    """The host's state machine over the declared cards of one run."""

    def __init__(self) -> None:
        self.cards: dict[str, Card] = {}
        self.moves: list[HypothesisMove] = []

    @property
    def declared(self) -> bool:
        return bool(self.cards)

    def declare(self, raw: dict[str, Any]) -> list[DeclaredHypothesis]:
        if self.cards:
            raise Declined("hypotheses are already declared; pass hypothesis_id with each check")
        cards = parse(raw)
        self.cards = {c.id: Card(c) for c in cards}
        return cards

    def open_cards(self) -> list[Card]:
        return [c for c in self.cards.values() if c.status == "open"]

    def resolve(self, hypothesis_id: str | None, tool: str, event_ref: str | None) -> Card | None:
        """The card a check tests: the one the model named, else the only card it can decide."""
        if hypothesis_id in self.cards:
            return self.cards[hypothesis_id]
        fits = [c for c in self.cards.values() if tool in DECISIVE.get(c.declared.kind, {})]
        if event_ref is not None:
            fits = [c for c in fits if c.declared.event_ref in (event_ref, None)]
        return fits[0] if len(fits) == 1 else None

    def observe(
        self,
        card: Card,
        call_id: str,
        tool: str,
        outcome: str | None,
        *,
        on_case: bool,
        event_ref: str | None = None,
        summary: str = "",
    ) -> HypothesisMove | None:
        """Attach a judged check to `card` and move it when the check can decide its kind."""
        card.checks.append(call_id)
        card.first_tool = card.first_tool or tool
        decisive = DECISIVE.get(card.declared.kind, {}).get(tool)
        if decisive is None or not on_case:
            return None
        if card.declared.kind == "event":
            if event_ref is None:
                return None
            if card.declared.event_ref is None:
                card.declared = card.declared.model_copy(update={"event_ref": event_ref})
            elif card.declared.event_ref != event_ref:
                return None
        supports, rules_out = decisive
        if outcome == supports:
            return self._move(card, "supported", f"{tool}: {outcome}. {summary}", call_id)
        if outcome == rules_out:
            return self._move(card, "ruled_out", f"{tool}: {outcome}. {summary}", call_id)
        if card.status == "open":
            return self._move(card, "inconclusive", f"{tool}: in between. {summary}", call_id)
        return None

    def observe_sql(self, card: Card, call_id: str, outcome: str | None, summary: str) -> HypothesisMove | None:
        """A self-written check may rule a card out, never support it."""
        card.checks.append(call_id)
        card.first_tool = card.first_tool or "sql_check"
        if outcome == "fails":
            return self._move(card, "ruled_out", f"sql_check: the prediction fails. {summary}", call_id)
        return None

    def settle(
        self, supported: list[EvidenceRef], ruled_out: list[RuledOut], placebo_outcome: str | None
    ) -> list[HypothesisMove]:
        """After the gate: event cards follow what the gate admitted (backfilled checks included), the
        recurring card follows the placebo, and what is still open was not tested."""
        moves: list[HypothesisMove] = []
        supported_refs = {e.ref for e in supported}
        ruled_refs = {r.evidence.ref for r in ruled_out if r.evidence is not None}
        for card in self.cards.values():
            d = card.declared
            target: HypothesisStatus | None = None
            reason = ""
            if d.kind == "event" and d.event_ref in supported_refs:
                target, reason = "supported", "the gate admitted its holdout as consistent"
            elif d.kind == "event" and d.event_ref in ruled_refs:
                target, reason = "ruled_out", "its holdout was refuted"
            elif d.kind == "recurring" and placebo_outcome in ("recurring", "unusual"):
                target = "supported" if placebo_outcome == "recurring" else "ruled_out"
                reason = f"placebo_test: {placebo_outcome}"
            if target is not None and target != card.status and card.status in ("open", "inconclusive"):
                moves.append(self._move(card, target, reason, None))
        for card in self.open_cards():
            moves.append(self._move(card, "not_tested", "no check decided it before the run ended", None))
        return moves

    def decisive_first(self) -> float | None:
        """Share of tested cards whose first check was one of the tools that can decide its kind."""
        tested = [c for c in self.cards.values() if c.first_tool is not None]
        if not tested:
            return None
        hits = sum(1 for c in tested if c.first_tool in DECISIVE.get(c.declared.kind, {}))
        return hits / len(tested)

    def _move(self, card: Card, status: HypothesisStatus, reason: str, call_id: str | None) -> HypothesisMove:
        card.status = status
        card.reason = reason.strip()[:300]
        move = HypothesisMove(id=card.id, status=status, reason=card.reason, call_id=call_id)
        self.moves.append(move)
        return move
