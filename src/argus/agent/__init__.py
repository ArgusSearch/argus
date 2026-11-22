"""Argus Agent: an autonomous LLM agent inside the investigation (docs/ext/agent.md).

The model chooses the next check before any verdict; deterministic code runs every check, gates the verdict
and checks every number. Business actions run only after human approval. `types.py` is the frozen interface
the other lanes code against.
"""
