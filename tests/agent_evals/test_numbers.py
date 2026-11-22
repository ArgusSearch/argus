from __future__ import annotations

import pytest

from argus.agent.numbers import FactBook, check


@pytest.mark.parametrize(
    ("text", "rejected_as"),
    [
        ("The estimated change was -129733.21%. [r12]", "unbacked"),
        ("The measured change was -36.25%. [r999]", "unknown_receipts"),
        ("The measured change was -36.25%.", "untagged"),
    ],
)
def test_e07_number_guard_refuses_invalid_drafts(text: str, rejected_as: str) -> None:
    facts = FactBook()
    facts.add({"change_pct": -36.25}, ["r12"])
    assert check("The measured change was -36.25%. [r12]", facts).ok
    rejected = check(text, facts)
    assert not rejected.ok and getattr(rejected, rejected_as)
