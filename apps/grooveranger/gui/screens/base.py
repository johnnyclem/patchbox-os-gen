"""The screen protocol.

A screen turns touches into ``Command`` values and renders the latest
``GrSnapshot``. It never holds the engine, never mutates a project, and
keeps nothing authoritative — everything it draws came from the last
``update``. Navigation and file work are not engine state, so they go
through the ``Host`` the App passes in rather than through commands.
"""
from __future__ import annotations

from typing import Protocol

import pygame

from core.commands import GrSnapshot
from rangerkit.gui.widgets import HitMap, RepeatRamp

LONG_PRESS_MS = 450


class Host(Protocol):
    """The App, as a screen sees it."""

    def now_ms(self) -> int: ...
    def set_tab(self, name: str) -> None: ...
    def message(self, text: str) -> None: ...
    def save_project(self) -> None: ...
    def new_project(self) -> None: ...
    def midi_ports(self) -> tuple: ...
    def refresh_ports(self) -> None: ...
    def bind_endpoint(self, endpoint: str, port: str) -> None: ...
    def set_theme(self, name: str) -> None: ...
    def cycle_theme(self) -> None: ...
    def learn_pot(self, index: int) -> None: ...
    def load_kit_step(self, direction: int) -> None: ...


class Screen:
    """Base class: press tracking, hold-to-repeat, no-op defaults."""

    #: Shown on the tab rail.
    title = "SCREEN"

    def __init__(self, host: Host, rect: pygame.Rect) -> None:
        self.host = host
        self.rect = rect
        self.hits = HitMap()
        self.snapshot: GrSnapshot | None = None
        self._pressed: str | None = None
        self._press_ms = 0
        self._ramp = RepeatRamp()

    # --- protocol -------------------------------------------------------------
    def handle(self, event: pygame.event.Event) -> list:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._pressed = self.hits.hit(event.pos)
            self._press_ms = self.host.now_ms()
            self._ramp.reset()
            return self.on_press(self._pressed) if self._pressed else []
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            key, self._pressed = self._pressed, None
            if key is None:
                return []
            if self.hits.hit(event.pos) != key:
                # The finger slid off: no action, but the control still needs
                # its release hook or a held pad never lifts.
                return self.on_release(key, moved_away=True)
            if self._ramp.count and self.repeats(key):
                return self.on_release(key)     # the hold stepped; lift is free
            held = self.host.now_ms() - self._press_ms
            actions = (self.on_long_press(key) if held >= LONG_PRESS_MS
                       else self.on_tap(key))
            return actions + self.on_release(key)
        return []

    def poll(self) -> list:
        """Ticked once a frame for the visible screen only."""
        key = self._pressed
        if key is None or not self.repeats(key):
            return []
        steps = self._ramp.due(self.host.now_ms(), self._press_ms)
        return self.on_repeat(key, steps) if steps else []

    def cancel_press(self) -> list:
        """Drop a held control without acting on it — the App calls this when
        a tab switch happens under a finger, which would otherwise leave a
        control latched and repeating into a hidden screen."""
        key, self._pressed = self._pressed, None
        self._ramp.reset()
        return self.on_release(key, moved_away=True) if key else []

    def update(self, snapshot: GrSnapshot) -> None:
        self.snapshot = snapshot

    def draw(self, surface: pygame.Surface) -> None:
        raise NotImplementedError

    # --- hooks ----------------------------------------------------------------
    def on_press(self, key: str) -> list:
        return []

    def on_tap(self, key: str) -> list:
        return []

    def on_long_press(self, key: str) -> list:
        """Default: a long press is still a tap."""
        return self.on_tap(key)

    def on_release(self, key: str, moved_away: bool = False) -> list:
        return []

    def repeats(self, key: str) -> bool:
        """Does holding this key ramp? Steppers opt in per key."""
        return False

    def on_repeat(self, key: str, steps: int) -> list:
        return []

    # --- helpers --------------------------------------------------------------
    def is_pressed(self, key: str) -> bool:
        return self._pressed == key

    def begin(self) -> None:
        """Clear the hit map before a frame's controls are registered."""
        self.hits.clear()


def cycle(sequence, current, step: int = 1):
    """The next value in a fixed vocabulary — the panel's enum control."""
    values = list(sequence)
    if current not in values:
        return values[0]
    return values[(values.index(current) + step) % len(values)]
