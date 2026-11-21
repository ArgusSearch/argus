"""The event hub: the bus between the runtime (or the replayer) and every SSE client.

`EventHub` is an `argus.runtime.bus.EventBus`, so a live `Runtime` publishes into it directly.
It folds every event into a `RunState`, keeps the history of the current stream for late joiners
and reconnects, and wakes the SSE handlers.

A stream has an id. Restarting a replay starts a new stream whose `seq` continues after the old one,
so `seq` stays strictly increasing for the whole process and a `Last-Event-ID` from an old stream is
recognisable: it lies before the new stream's first seq. Such a client, and every client connected
during the restart, first gets a `stream` item and then the new stream from its first event.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from argus.api.state import RunState
from argus.contracts.events import Event
from argus.runtime.bus import EventBus


@dataclass(frozen=True)
class StreamItem:
    """One item for an SSE client: an event, or the start of a new stream (`event is None`)."""

    stream: str
    event: Event | None


def _new_stream_id() -> str:
    return uuid.uuid4().hex[:8]


class EventHub(EventBus):
    def __init__(self, state: RunState) -> None:
        super().__init__()
        self.state = state
        self.stream = _new_stream_id()
        self.base_seq = 0  # every seq of the current stream is greater than this
        self._loop: asyncio.AbstractEventLoop | None = None
        self._changed: asyncio.Event | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attach the server's event loop (called once at startup)."""
        self._loop = loop
        self._changed = asyncio.Event()

    # ------------------------------------------------------------------ writers (any thread)

    def publish(self, event: Event) -> None:
        with self._lock:
            last = self.history[-1].seq if self.history else self.base_seq
            if event.seq <= last:
                raise ValueError(f"event seq {event.seq} is not after {last}")
            self.history.append(event)
            self.state.apply(event)
            subs = list(self._subs)
        for loop, queue in subs:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        self._notify()

    def next_seq(self) -> int:
        return self.last_seq + 1

    def reset(self) -> str:
        """Start a new stream (replay restart): drop the history and the folded state. Returns its id."""
        with self._lock:
            self.base_seq = self.history[-1].seq if self.history else self.base_seq
            self.history = []
            self.stream = _new_stream_id()
            self.state.reset()
        self._notify()
        return self.stream

    def _notify(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._wake()
        else:
            loop.call_soon_threadsafe(self._wake)

    def _wake(self) -> None:
        if self._changed is not None:
            self._changed.set()
            self._changed = asyncio.Event()

    # ------------------------------------------------------------------ readers

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self.history[-1].seq if self.history else self.base_seq

    async def follow(self, after: int = 0) -> AsyncIterator[StreamItem]:
        """Yield the history after seq `after`, then live events, until the client goes away.

        A restart while following, or an `after` from an older stream, yields a `stream` item first and
        then the new stream from its first event.
        """
        current: str | None = None
        sent = 0  # index into the history of `current`
        while True:
            changed = self._changed
            pending: list[StreamItem] = []
            with self._lock:  # the runtime appends from its own thread: read and advance together
                stream, history = self.stream, self.history
                if current is None:
                    if after and after <= self.base_seq:
                        pending.append(StreamItem(stream, None))  # the client knows an older stream
                        sent = 0
                    else:
                        sent = sum(1 for e in history if e.seq <= after)
                elif stream != current:
                    pending.append(StreamItem(stream, None))
                    sent = 0
                current = stream
                pending += [StreamItem(stream, e) for e in history[sent:]]
                sent = len(history)
            for item in pending:
                yield item
            if changed is None:
                return
            await changed.wait()
