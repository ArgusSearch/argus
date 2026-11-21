"""LLM wrapper (lane B, Stage 2). Optional at runtime: everything works without ANTHROPIC_API_KEY.

Rules: the LLM never produces a number or a verdict. It may propose edges (cartographer), propose
hypotheses as typed C6 tool calls (planner), and write report prose that must pass
`argus.narrator.report.unbacked_numbers`, otherwise the template report is used.
Planned shape: one model per role, JSON-schema outputs, timeout, cost counter, record and replay, global off switch.
"""
