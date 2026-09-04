"""Tiny in-process event stream for immediate dashboard inbox updates.

SQLite remains the source of truth. Events only tell an already-open browser
to re-read /api/inbox now instead of waiting for its 15-second safety poll.
"""
import asyncio
import json
from collections.abc import AsyncIterator


_subscribers: set[asyncio.Queue] = set()


def publish(event: dict) -> None:
    for queue in tuple(_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # The browser always reloads the authoritative SQLite-backed inbox;
            # one signal is enough even if several replies arrive together.
            pass


async def stream() -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    _subscribers.add(queue)
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            except TimeoutError:
                yield ": keepalive\n\n"
    finally:
        _subscribers.discard(queue)
