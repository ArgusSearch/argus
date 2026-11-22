"""FakeLlmClient: an `LlmClient` that answers from a script, for tests and adversarial recordings."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from argus.agent.types import LlmRequest, LlmResponse


class ScriptExhausted(RuntimeError):
    pass


class FakeLlmClient:
    """Returns `responses` in order, or calls `responder(request)`. Keeps every request it saw."""

    def __init__(
        self,
        responses: Sequence[LlmResponse] = (),
        responder: Callable[[LlmRequest], LlmResponse] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.responder = responder
        self.requests: list[LlmRequest] = []

    def create(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if self.responder is not None:
            return self.responder(request)
        if not self.responses:
            raise ScriptExhausted(f"no scripted response for {request.key}")
        return self.responses.pop(0)


def tool_use(
    name: str, args: dict[str, object], text: str = "", model: str = "claude-sonnet-5-5", n: int = 1
) -> LlmResponse:
    """A scripted turn: an optional visible sentence, then one tool call."""
    content: list[dict[str, object]] = [{"type": "text", "text": text}] if text else []
    content.append({"type": "tool_use", "id": f"toolu_fake_{n}", "name": name, "input": args})
    return LlmResponse(
        model=model,
        content=content,
        stop_reason="tool_use",
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )
