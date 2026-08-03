"""Per-track undo — a stack of phrases, because phrases are values.

Every destructive moment (an overdub take landing, a reverse, a stretch, a
clear, a decay pass crossing a take boundary) pushes the *previous* phrase.
Undo pops. The depth is bounded per track so eight tracks of eight-bar
takes cannot quietly eat the RAM of an appliance that runs for weeks.
"""
from __future__ import annotations

from core.phrase import Phrase

DEPTH = 16


class History:
    def __init__(self) -> None:
        self._stacks: dict[int, list[Phrase]] = {}

    def push(self, track: int, phrase: Phrase) -> None:
        stack = self._stacks.setdefault(track, [])
        stack.append(phrase)
        if len(stack) > DEPTH:
            stack.pop(0)

    def pop(self, track: int) -> Phrase | None:
        stack = self._stacks.get(track)
        return stack.pop() if stack else None

    def depth(self, track: int) -> int:
        return len(self._stacks.get(track, ()))

    def clear(self, track: int | None = None) -> None:
        if track is None:
            self._stacks.clear()
        else:
            self._stacks.pop(track, None)
