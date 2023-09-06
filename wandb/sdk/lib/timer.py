import time
from typing import Any


class Timer:
    def __init__(self) -> None:
        self.start_time: float = time.time()
        self.start: float = time.perf_counter()
        self.stop: float = self.start

    def __enter__(self) -> "Timer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return self.stop - self.start
