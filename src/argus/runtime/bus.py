"""In-process event bus. The runtime publishes from its own thread; SSE clients subscribe from asyncio."""

from __future__ import annotations

import asyncio
import threading

from argus.contracts.events import Event


class EventBus:
    def __init__(self) -> None:
        self.history: list[Event] = []
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Event]]] = []
        self._lock = threading.Lock()

    def publish(self, event: Event) -> None:
        with self._lock:
            self.history.append(event)
            subs = list(self._subs)
        for loop, queue in subs:
            loop.call_soon_threadsafe(queue.put_nowait, event)

    def subscribe(self) -> tuple[asyncio.Queue[Event], list[Event]]:
        """Call from inside the event loop. Returns a live queue and the history published so far."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), queue))
            return queue, list(self.history)

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        with self._lock:
            self._subs = [(lp, q) for lp, q in self._subs if q is not queue]

    def next_seq(self) -> int:
        with self._lock:
            return len(self.history) + 1
