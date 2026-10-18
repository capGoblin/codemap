"""Run limits: wall time, tokens, cost and tool calls."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from codemap.agents.model import ModelResponse


@dataclass(frozen=True)
class Limits:
    wall_seconds: int
    max_tokens: int
    max_cost_usd: float
    max_tool_calls: int


class LimitReached(Exception):  # noqa: N818 - name fixed by the plan
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Budget:
    """Shared by concurrent steps, so every update takes the lock.

    Prices are USD per MTok. With no price the cost stays 0 and the cost limit is skipped.
    """

    def __init__(
        self,
        limits: Limits,
        price_in: float | None,
        price_out: float | None,
        clock: Callable[[], float] = time.monotonic,
        cancel: threading.Event | None = None,
    ) -> None:
        self._limits = limits
        self._price_in = price_in
        self._price_out = price_out
        self._clock = clock
        self._cancel = cancel
        self._start = clock()
        self._lock = threading.Lock()
        self._input = 0
        self._output = 0
        self._tool_calls = 0

    def charge(self, resp: ModelResponse) -> None:
        with self._lock:
            self._input += resp.input_tokens
            self._output += resp.output_tokens

    def count_tool_call(self) -> None:
        with self._lock:
            self._tool_calls += 1

    @property
    def input_tokens(self) -> int:
        with self._lock:
            return self._input

    @property
    def output_tokens(self) -> int:
        with self._lock:
            return self._output

    @property
    def cost_usd(self) -> float:
        with self._lock:
            return self._cost()

    def _cost(self) -> float:
        if self._price_in is None or self._price_out is None:
            return 0.0
        return (self._input * self._price_in + self._output * self._price_out) / 1_000_000

    def exhausted(self) -> bool:
        """True when `check` would raise now."""
        try:
            self.check()
        except LimitReached:
            return True
        return False

    def check(self) -> None:
        """Raise before a model call when a limit is hit or the user cancelled."""
        if self._cancel is not None and self._cancel.is_set():
            raise LimitReached("cancelled")
        with self._lock:
            lim = self._limits
            if self._clock() - self._start >= lim.wall_seconds:
                raise LimitReached("wall time")
            if self._input + self._output >= lim.max_tokens:
                raise LimitReached("tokens")
            if self._cost() >= lim.max_cost_usd:
                raise LimitReached("cost")
            if self._tool_calls >= lim.max_tool_calls:
                raise LimitReached("tool calls")
