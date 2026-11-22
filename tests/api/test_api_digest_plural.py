from __future__ import annotations

import pytest

from argus.api.digest import _plural


@pytest.mark.parametrize(
    ("n", "word", "expected"),
    [
        (0, "anomaly", "0 anomalies"),
        (1, "anomaly", "1 anomaly"),
        (2, "anomaly", "2 anomalies"),
        (3, "late-data delay", "3 late-data delays"),
        (0, "hour", "0 hours"),
        (1, "alert", "1 alert"),
        (2, "planned or harmless change", "2 planned or harmless changes"),
    ],
)
def test_plural(n: int, word: str, expected: str) -> None:
    assert _plural(n, word) == expected
