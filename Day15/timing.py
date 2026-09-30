"""Tiny per-step profiler: `with t.step("retrieval"): ...` then `t.report()` for logs/response."""
import time
from contextlib import contextmanager


class StepTimer:
    def __init__(self):
        self._start = time.perf_counter()
        self.steps: dict[str, float] = {}

    @contextmanager
    def step(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:  # record even when the step raises, so failures show where time went
            self.steps[name] = self.steps.get(name, 0.0) + (time.perf_counter() - started) * 1000

    def report(self) -> dict[str, float]:
        total = (time.perf_counter() - self._start) * 1000
        return {**{k: round(v, 1) for k, v in self.steps.items()}, "total_ms": round(total, 1)}

    def slowest(self) -> str | None:
        return max(self.steps, key=self.steps.get) if self.steps else None
