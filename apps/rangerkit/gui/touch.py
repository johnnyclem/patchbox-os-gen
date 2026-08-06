"""Touch input — SDL finger events, translated into the mouse events every
screen already speaks.

The suite GUIs (and RangerDeck) are written against ``MOUSEBUTTONDOWN`` /
``MOUSEBUTTONUP``. On the appliance that is not what the panel produces:
capacitive USB-HID bars (ElecLab 1280×400 and kin) emit ``FINGERDOWN`` /
``FINGERUP`` only. Relying on SDL's synthesis hint is a poor thing for a
kiosk to lean on:

* it is a **hint** (``SDL_TOUCH_MOUSE_EVENTS``) — the service unit pins it
  to ``0`` so a palm cannot steal the pointer, which means without this
  module every tap is silently dropped and the panel looks perfect;
* SDL decides which contact becomes "the mouse", so a second finger or a
  palm on a bar panel can interleave presses on a UI that only understands
  one;
* and when taps do nothing there is no way to tell *no touch device* from
  *touch device, nobody tapped* — two faults with completely different
  fixes.

So the app pins the hint off and does the translation here, where it can
be tested off-hardware. One contact owns the pointer until it lifts;
everything else is dropped.

Set ``RANGER_TOUCH=sdl`` to hand the job back to SDL — the bisect to run
when a panel misbehaves and you need to know which side of this module is
at fault.
"""
from __future__ import annotations

import os

import pygame

#: SDL's hint name. SDL reads hints from the environment under exactly this
#: name, which is the only lever pygame gives us before video init.
HINT_TOUCH_MOUSE = "SDL_TOUCH_MOUSE_EVENTS"
MODE_ENV = "RANGER_TOUCH"
MODES = ("native", "sdl")

FINGER_EVENTS = (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION)
POINTER_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                  pygame.MOUSEMOTION)


def configure() -> str:
    """Pick the touch path and tell SDL about it. Call *before* display init.

    Returns the mode in force so the caller can log it: "which of the two
    paths is this unit on" is the first question when a panel stops
    responding, and the answer has to be in the journal, not in someone's
    memory of what the default was.
    """
    mode = os.environ.get(MODE_ENV, "native").strip().lower()
    if mode not in MODES:
        mode = "native"
    os.environ[HINT_TOUCH_MOUSE] = "0" if mode == "native" else "1"
    return mode


def num_devices() -> int:
    """Touch devices SDL can see, or -1 when SDL cannot be asked.

    Zero here is the signature of the commonest appliance fault by far: the
    service user cannot open ``/dev/input/event*``, so SDL's evdev backend
    enumerates nothing while the KMS panel keeps rendering perfectly.
    """
    try:
        from pygame._sdl2 import touch
        return int(touch.get_num_devices())
    except Exception:               # pragma: no cover - SDL build w/o _sdl2
        return -1


class TouchTranslator:
    """Finger events in, mouse events out — one contact at a time."""

    def __init__(self, size: tuple[int, int], mode: str = "native") -> None:
        self.width, self.height = size
        self.native = mode != "sdl"
        self.finger: int | None = None      # the contact that owns the pointer
        self.taps = 0
        self.dropped = 0                    # extra contacts, ignored
        self._pos = (0, 0)

    def resize(self, size: tuple[int, int]) -> None:
        """Keep pixel math honest after a display reopen (deck handover)."""
        self.width, self.height = size

    def status(self) -> str:
        """One line for logs / a diagnostics strip."""
        devices = num_devices()
        if not self.native:
            return f"sdl · {self.taps} taps"
        seen = "? devices" if devices < 0 else f"{devices} device(s)"
        return f"{seen} · {self.taps} taps"

    def healthy(self) -> bool:
        """False when SDL sees no touch hardware at all — worth colouring."""
        return num_devices() != 0

    def translate(self, event: pygame.event.Event
                  ) -> pygame.event.Event | None:
        """The event a screen should see, or None to swallow it."""
        if not self.native:
            return event
        if event.type in POINTER_EVENTS and getattr(event, "touch", False):
            # The hint is off, so SDL should not be synthesising these. If a
            # build does it anyway, dropping them here is what keeps one tap
            # from being counted — and acted on — twice.
            return None
        if event.type not in FINGER_EVENTS:
            return event
        return self._from_finger(event)

    def _from_finger(self, event: pygame.event.Event
                     ) -> pygame.event.Event | None:
        finger = getattr(event, "finger_id", 0)
        if event.type == pygame.FINGERDOWN:
            if self.finger is not None and finger != self.finger:
                self.dropped += 1       # a palm or a second finger, not a tap
                return None
            # Same id going down twice means we missed its release (a glitchy
            # panel, or a mode switch under a held finger). Re-press rather
            # than latch: a stuck pointer would eat every tap that follows.
            self.finger = finger
            self.taps += 1
            self._pos = pos = self._point(event)
            return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                      pos=pos, touch=True)
        if finger != self.finger:
            return None
        previous, self._pos = self._pos, self._point(event)
        pos = self._pos
        if event.type == pygame.FINGERMOTION:
            return pygame.event.Event(
                pygame.MOUSEMOTION, pos=pos,
                rel=(pos[0] - previous[0], pos[1] - previous[1]),
                buttons=(1, 0, 0), touch=True)
        self.finger = None
        return pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos,
                                  touch=True)

    def _point(self, event: pygame.event.Event) -> tuple[int, int]:
        """SDL reports finger position normalised 0..1; the UI wants pixels."""
        x = _unit(getattr(event, "x", 0.0))
        y = _unit(getattr(event, "y", 0.0))
        return (min(int(x * self.width), self.width - 1),
                min(int(y * self.height), self.height - 1))


def _unit(value: float) -> float:
    # A panel whose evdev axis range is wrong can report outside 0..1. Clamp
    # rather than drop: an edge tap that lands on the edge button is a better
    # failure than a dead corner.
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0
