"""Mix vs rate split of a blended ratio Y = sum_k w_k * r_k (w = segment share, r = segment rate).

With midpoint averages the split is exact:

    dY = sum_k dw_k * mean(r_k)  (mix)  +  sum_k mean(w_k) * dr_k  (rate)

If mix dominates and every segment's own rate is flat, the change is an innocent mix shift
(Simpson's paradox, scenario S5) and the verdict is EXPECTED.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MixRate:
    change: float
    mix: float
    rate: float
    per_cell: dict[str, tuple[float, float]]  # key -> (mix effect, rate effect)

    @property
    def residual(self) -> float:
        return self.change - self.mix - self.rate


def mix_rate_split(
    num0: dict[str, float], den0: dict[str, float], num1: dict[str, float], den1: dict[str, float]
) -> MixRate:
    """Split the blended rate change from per-segment numerators and denominators."""
    keys = sorted(set(den0) | set(den1))
    d0, d1 = sum(den0.values()), sum(den1.values())
    y0 = sum(num0.values()) / d0
    y1 = sum(num1.values()) / d1
    mix = rate = 0.0
    per_cell = {}
    for k in keys:
        w0, w1 = den0.get(k, 0.0) / d0, den1.get(k, 0.0) / d1
        r0 = num0.get(k, 0.0) / den0[k] if den0.get(k) else 0.0
        r1 = num1.get(k, 0.0) / den1[k] if den1.get(k) else 0.0
        m, r = (w1 - w0) * (r0 + r1) / 2, (w0 + w1) / 2 * (r1 - r0)
        per_cell[k] = (m, r)
        mix += m
        rate += r
    return MixRate(change=y1 - y0, mix=mix, rate=rate, per_cell=per_cell)
