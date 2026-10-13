from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any


@dataclasses.dataclass(frozen=True)
class PhaseDuration:
    phase: str
    step: int | None
    duration_ms: float


@dataclasses.dataclass(eq=False)
class Token:
    start: Any
    phase: str
    step: int | None


class CudaEventQueue:
    def __init__(self, event_factory: Callable[[], Any], capacity: int = 128) -> None:
        self._factory = event_factory
        self._capacity = capacity
        self._pending: list[tuple[Token, Any]] = []
        self._active: set[Token] = set()
        self.dropped = 0

    def start(self, phase: str, step: int | None) -> Token | None:
        if len(self._pending) + len(self._active) >= self._capacity:
            self.dropped += 1
            return None
        event = self._factory()
        event.record()
        token = Token(event, phase, step)
        self._active.add(token)
        return token

    def finish(self, token: Token | None) -> None:
        if token is None or token not in self._active:
            return
        self._active.remove(token)
        event = self._factory()
        event.record()
        self._pending.append((token, event))

    def completed(self) -> list[PhaseDuration]:
        result = []
        pending = []
        for token, end in self._pending:
            if end.query():
                result.append(
                    PhaseDuration(
                        token.phase, token.step, token.start.elapsed_time(end)
                    )
                )
            else:
                pending.append((token, end))
        self._pending = pending
        return result

    def close(self) -> None:
        self.dropped += len(self._pending) + len(self._active)
        self._pending.clear()
        self._active.clear()
