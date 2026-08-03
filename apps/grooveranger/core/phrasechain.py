"""Song mode — a chain of (pattern, passes) entries.

When the chain is on, each entry holds its pattern for so many passes, then
the next pattern is queued through the sequencer's ordinary pass-end switch
— song mode is a hand pressing pattern buttons on schedule, nothing deeper,
which is why everything that holds for live pattern switching (fills,
conditions, queued edits) holds in a song too. The chain loops.
"""
from __future__ import annotations


class Chain:
    def __init__(self) -> None:
        self.entries: list[tuple[int, int]] = []     # (pattern, passes)
        self.on = False
        self.position = 0
        self.passes_done = 0

    def append(self, pattern: int, passes: int = 4) -> None:
        self.entries.append((int(pattern), max(1, min(64, int(passes)))))

    def remove(self, position: int) -> None:
        if 0 <= position < len(self.entries):
            del self.entries[position]
            self.position = min(self.position,
                                max(0, len(self.entries) - 1))

    def clear(self) -> None:
        self.entries.clear()
        self.stop()

    def start(self) -> int | None:
        """Arm the chain; returns the first pattern or None when empty."""
        if not self.entries:
            self.on = False
            return None
        self.on = True
        self.position = 0
        self.passes_done = 0
        return self.entries[0][0]

    def stop(self) -> None:
        self.on = False
        self.position = 0
        self.passes_done = 0

    def on_pass_end(self) -> int | None:
        """Called each pattern pass; returns a pattern to queue when this
        entry's passes are spent."""
        if not self.on or not self.entries:
            return None
        self.passes_done += 1
        if self.passes_done < self.entries[self.position][1]:
            return None
        self.passes_done = 0
        self.position = (self.position + 1) % len(self.entries)
        return self.entries[self.position][0]

    def to_config(self) -> dict:
        return {"entries": [list(e) for e in self.entries], "on": self.on}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Chain":
        chain = cls()
        raw = raw or {}
        for pattern, passes in raw.get("entries", []):
            chain.append(int(pattern), int(passes))
        # ``on`` is deliberately not restored: a project load should not
        # start a song marching before anyone pressed play.
        return chain
