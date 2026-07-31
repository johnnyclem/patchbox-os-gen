"""Inky Impression side buttons A/B/C/D via gpiod (Pi 5 header BCM 5/6/16/24)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator

# BCM numbers for Impression buttons top→bottom (Pimoroni docs / buttons.py)
BUTTON_A = 5
BUTTON_B = 6
BUTTON_C = 16
BUTTON_D = 24
BUTTONS = (BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D)
LABELS = {BUTTON_A: "A", BUTTON_B: "B", BUTTON_C: "C", BUTTON_D: "D"}


@dataclass
class ButtonEvent:
    label: str  # A/B/C/D
    gpio: int
    t: float


class ButtonReader:
    """Blocking / timeout edge reader. No-op fallback when GPIO unavailable."""

    def __init__(self, simulate: bool = False) -> None:
        self.simulate = simulate
        self._request = None
        self._offsets: list[int] = []
        self._offset_to_gpio: dict[int, int] = {}
        if not simulate:
            self._setup()

    def _setup(self) -> None:
        try:
            import gpiod
            import gpiodevice
            from gpiod.line import Bias, Direction, Edge

            chip = gpiodevice.find_chip_by_platform()
            settings = gpiod.LineSettings(
                direction=Direction.INPUT,
                bias=Bias.PULL_UP,
                edge_detection=Edge.FALLING,
                debounce_period=timedelta(milliseconds=20),
            )
            offsets = []
            for gpio in BUTTONS:
                off = chip.line_offset_from_id(gpio)
                offsets.append(off)
                self._offset_to_gpio[off] = gpio
            self._offsets = offsets
            config = dict.fromkeys(offsets, settings)
            self._request = chip.request_lines(consumer="patchbox-inky", config=config)
        except Exception as exc:  # noqa: BLE001
            print(f"Button GPIO unavailable ({exc}); button input disabled")
            self._request = None

    def wait(self, timeout_s: float | None = None) -> ButtonEvent | None:
        """Wait up to timeout_s for a press. None on timeout / no hardware."""
        if self._request is None:
            if timeout_s and timeout_s > 0:
                time.sleep(min(timeout_s, 0.5))
            return None
        try:
            td = None if timeout_s is None else timedelta(seconds=timeout_s)
            if not self._request.wait_edge_events(td):
                return None
            for event in self._request.read_edge_events():
                gpio = self._offset_to_gpio.get(event.line_offset)
                if gpio is None:
                    continue
                return ButtonEvent(label=LABELS[gpio], gpio=gpio, t=time.time())
        except Exception as exc:  # noqa: BLE001
            print(f"Button read error: {exc}")
        return None

    def poll_all(self, timeout_s: float = 0.05) -> Iterator[ButtonEvent]:
        ev = self.wait(timeout_s)
        if ev:
            yield ev

    def close(self) -> None:
        self._request = None
