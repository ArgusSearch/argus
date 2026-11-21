"""The frozen interface: every example validates and round-trips through JSON; the fake client works."""

from __future__ import annotations

import pytest

from argus.agent import types
from argus.agent.examples import EXAMPLES, REQUEST
from argus.agent.fake import FakeLlmClient, ScriptExhausted, tool_use


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_round_trips(name: str) -> None:
    model = getattr(types, name)
    example = EXAMPLES[name]
    assert type(example) is model
    assert model.model_validate_json(example.model_dump_json()) == example


def test_every_public_model_has_an_example() -> None:
    models = {
        n
        for n, v in vars(types).items()
        if isinstance(v, type)
        and issubclass(v, types.BaseModel)
        and v.__module__ == types.__name__
        and not n.startswith("_")
    }
    assert models == set(EXAMPLES) | {"GateResult", "SuccessRule"}


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(types.ValidationError if hasattr(types, "ValidationError") else Exception):
        types.ReceiptLink.model_validate({"run_id": "r", "world_revision": "factual", "receipt_id": "a1", "x": 1})


def test_fake_client_replays_in_order() -> None:
    client = FakeLlmClient([tool_use("list_events", {}, "first")])
    assert client.create(REQUEST).content[-1]["name"] == "list_events"
    with pytest.raises(ScriptExhausted):
        client.create(REQUEST)
    assert len(client.requests) == 2
