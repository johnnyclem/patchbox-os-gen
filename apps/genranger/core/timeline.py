"""The timeline — "do that thing you did two minutes ago" as a control.

A ring of the last N captured states (the same dict shape seeds store),
pushed whenever a mutation batch lands and coalesced to at most one entry
per bar. Stepping back restores a state *without* truncating the ring, so
the player can walk both ways until new mutations overwrite the head —
reversible is the PRD's word, and reversible means both directions.
"""
from __future__ import annotations

CAPACITY = 32


class Timeline:
    def __init__(self) -> None:
        self._entries: list[tuple[int, dict]] = []      # (bar, state)
        self.position = -1          # -1 = live (the head)

    def __len__(self) -> int:
        return len(self._entries)

    def push(self, bar: int, state: dict) -> None:
        """Record a state at a bar. A second push in the same bar replaces
        the first — one entry per bar keeps 32 entries meaning minutes, not
        milliseconds."""
        if self._entries and self._entries[-1][0] == bar:
            self._entries[-1] = (bar, state)
        else:
            self._entries.append((bar, state))
            if len(self._entries) > CAPACITY:
                self._entries.pop(0)
        self.position = -1          # any new history returns you to live

    def step(self, delta: int) -> dict | None:
        """Move through history. Returns the state to apply, or None at the
        edges (the panel shows the bump; nothing changes)."""
        if not self._entries:
            return None
        here = len(self._entries) - 1 if self.position < 0 else self.position
        there = max(0, min(len(self._entries) - 1, here + delta))
        if there == here and self.position >= 0:
            return None
        self.position = there
        return self._entries[there][1]

    def live(self) -> dict | None:
        """Return to the head of history."""
        if self.position < 0 or not self._entries:
            self.position = -1
            return None
        self.position = -1
        return self._entries[-1][1]

    def bars(self) -> tuple[int, ...]:
        return tuple(bar for bar, _state in self._entries)
