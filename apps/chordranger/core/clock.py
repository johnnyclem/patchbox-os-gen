"""The injectable timebase.

``RealClock`` sleeps toward absolute deadlines, so a late wake-up is repaid by
the next tick arriving early rather than by the whole song drifting. A missed
deadline is left in the past and the engine runs catch-up ticks back to back —
music that stutters once recovers its position, music that drifts never does.

``FakeClock`` advances instantly, which is what makes the engine testable: a
test can run four bars of arranger output in microseconds and assert on the
exact ticks, with no sleeping and no flakiness.
"""
from __future__ import annotations

import time

PULSES_PER_QUARTER = 24         # MIDI clock (0xF8) rate, fixed by the spec


class RealClock:
    """Absolute-deadline sleeper on ``time.monotonic_ns``."""

    def __init__(self) -> None:
        self._deadline_ns: int | None = None

    def wait_for_tick(self, tick_ns: int) -> None:
        if self._deadline_ns is None:
            self._deadline_ns = time.monotonic_ns()
            return
        self._deadline_ns += tick_ns
        while (remaining := self._deadline_ns - time.monotonic_ns()) > 0:
            time.sleep(remaining / 1e9)

    def now_ns(self) -> int:
        return time.monotonic_ns()

    def resync(self) -> None:
        """Forget the accumulated deadline — called on transport start and on
        a tempo change large enough that catching up would be a burst of
        machine-gun notes rather than a recovery."""
        self._deadline_ns = None


class FakeClock:
    """Deterministic timebase for tests and benches."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def wait_for_tick(self, tick_ns: int) -> None:
        self._now_ns += tick_ns

    def now_ns(self) -> int:
        return self._now_ns

    def resync(self) -> None:
        pass


def tick_ns(bpm: float, ppqn: int) -> int:
    """Nanoseconds per engine tick at *bpm*.

    Integer nanoseconds, computed from the tempo each time rather than
    accumulated, so a long set cannot slowly diverge from the drummer.
    """
    return int(60e9 / (max(1.0, bpm) * ppqn))


class ExternalClock:
    """MIDI clock follower: 24 PPQN in, engine ticks out.

    Each 0xF8 credits a fixed number of engine ticks; the engine spends the
    credit through its normal tick path so external sync is not a second
    playback implementation. The tempo readout is an EMA because a display
    that flickers between 119 and 121 is worse than one that lags slightly.
    """

    def __init__(self, ppqn: int, smooth: float = 0.2,
                 dropout_ms: float = 1000.0) -> None:
        self.ticks_per_pulse = max(1, ppqn // PULSES_PER_QUARTER)
        self._smooth = min(1.0, max(0.0, smooth))
        self._dropout_ns = int(dropout_ms * 1e6)
        self._last_ns: int | None = None
        self._bpm: float | None = None

    def on_pulse(self, now_ns: int) -> int:
        if self._last_ns is not None:
            delta = now_ns - self._last_ns
            if delta > 0:
                bpm = 60e9 / (delta * PULSES_PER_QUARTER)
                self._bpm = bpm if self._bpm is None else \
                    self._bpm + self._smooth * (bpm - self._bpm)
        self._last_ns = now_ns
        return self.ticks_per_pulse

    @property
    def bpm(self) -> float | None:
        return self._bpm

    def timed_out(self, now_ns: int) -> bool:
        return (self._last_ns is not None
                and now_ns - self._last_ns > self._dropout_ns)

    def reset(self) -> None:
        """A transport edge is not a tempo sample."""
        self._last_ns = None
