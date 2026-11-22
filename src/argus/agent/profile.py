"""Agent profiles: `v1` is the sealed loop, `v2` switches on the agent-intelligence techniques one by one.

`v1` is the default and must stay byte-identical: same prompt, same tool schemas, same activity lines, so
the sealed recordings under `fixtures/agent/v1/` keep replaying strictly. Everything new runs only in `v2`,
each technique behind one feature name so a single technique can be cut without touching the others:

| feature          | what it switches on                                                             |
|------------------|---------------------------------------------------------------------------------|
| `critic`         | a second model in a fresh context tries to falsify a supported cause           |
| `sql`            | `sql_check` for both models when the SQL gate is installed                     |
| `hypotheses`     | `propose_hypotheses`: 2-5 competing hypotheses before the first causal check    |
| `memory`         | the case packet's `experience` block (advice, never evidence)                   |
| `second_opinion` | the STL second opinion (advisory)                                               |

`ARGUS_AGENT_PROFILE` picks the profile (`v1` or `v2`); `ARGUS_AGENT_FEATURES` narrows `v2` to a
comma-separated subset (an empty value means none, which makes `v2` behave as `v1`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from argus.agent.types import FEATURES, Feature, ProfileName

V2_DEFAULT: tuple[Feature, ...] = ("critic", "sql", "hypotheses")


@dataclass(frozen=True)
class Profile:
    name: ProfileName
    features: frozenset[Feature] = frozenset()

    def on(self, feature: Feature) -> bool:
        return feature in self.features

    def to_json(self) -> dict[str, object]:
        return {"profile": self.name, "features": sorted(self.features)}

    @classmethod
    def of(cls, name: str, features: str | list[str] | tuple[str, ...] | None = None) -> Profile:
        """`v1` (features ignored) or `v2` with `features` (None: the v2 default set)."""
        if name == "v1":
            return V1
        if name != "v2":
            raise ValueError(f"agent profile must be 'v1' or 'v2', got {name!r}")
        if features is None:
            return V2
        items = [f.strip() for f in features.split(",")] if isinstance(features, str) else list(features)
        chosen = [f for f in items if f]
        unknown = sorted(set(chosen) - set(FEATURES))
        if unknown:
            raise ValueError(f"unknown agent feature(s) {unknown}; known: {list(FEATURES)}")
        return cls("v2", frozenset(chosen))  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, name: str | None = None, features: str | None = None) -> Profile:
        return cls.of(
            name if name is not None else (os.environ.get("ARGUS_AGENT_PROFILE") or "v1").strip().lower(),
            features if features is not None else os.environ.get("ARGUS_AGENT_FEATURES"),
        )


V1 = Profile("v1")
V2 = Profile("v2", frozenset(V2_DEFAULT))
