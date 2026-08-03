"""ARRANGE — a chain of scenes, played in order.

The written half of the free-form session: an ordered list of
``(scene, bars)`` entries. When the chain runs, each entry launches its
scene and holds it for its bar count, then the next entry fires — the
whole set, hands free, but every scene still launches through the same
quantized path a finger would use.
"""
from __future__ import annotations

MAX_ENTRIES = 16


class Chain:
    def __init__(self) -> None:
        self.entries: list[tuple[int, int]] = []    # (scene, bars)
        self.on = False
        self.position = -1          # entry currently holding
        self._held_bars = 0

    def append(self, scene: int, bars: int) -> bool:
        if len(self.entries) >= MAX_ENTRIES:
            return False
        self.entries.append((int(scene), max(1, min(32, int(bars)))))
        return True

    def remove(self, position: int) -> None:
        if 0 <= position < len(self.entries):
            self.entries.pop(position)
            if self.position >= len(self.entries):
                self.position = -1

    def clear(self) -> None:
        self.entries.clear()
        self.position = -1
        self.on = False

    def start(self) -> int | None:
        """Arm the chain. Returns the first scene to launch."""
        if not self.entries:
            self.on = False
            return None
        self.on = True
        self.position = 0
        self._held_bars = 0
        return self.entries[0][0]

    def stop(self) -> None:
        self.on = False
        self.position = -1

    def on_bar(self) -> int | None:
        """A bar elapsed. Returns the next scene to launch, or None to hold.
        The chain wraps — a set that ends is a set that stopped on purpose,
        with the chain switch, not by running off the page."""
        if not self.on or self.position < 0:
            return None
        self._held_bars += 1
        _scene, bars = self.entries[self.position]
        if self._held_bars < bars:
            return None
        self.position = (self.position + 1) % len(self.entries)
        self._held_bars = 0
        return self.entries[self.position][0]

    def to_config(self) -> list:
        return [[scene, bars] for scene, bars in self.entries]

    @classmethod
    def from_config(cls, raw) -> "Chain":
        chain = cls()
        for entry in raw or ():
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                chain.append(int(entry[0]), int(entry[1]))
        return chain
