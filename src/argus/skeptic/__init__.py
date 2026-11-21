"""Skeptic (lane B, Stage 2): try to refute a finished investigation before it is reported.

Deterministic checks first (placebo on the same hours of 8 earlier weeks, holdout, decoys, reverse lag),
then optionally a model in its own context that sees only the evidence. Writes `Findings.skeptic`
(C4 `SkepticResult`) and emits `skeptic_step` events (C5, reserved).
"""
