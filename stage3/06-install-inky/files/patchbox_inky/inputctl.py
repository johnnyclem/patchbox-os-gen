"""Unified input: Inky side buttons A–D + keyboard (no touch screen).

Keyboard map (also printed at UI start)::

    ↑ / k / w     → A (up)
    ↓ / j / s     → B (down)
    Enter / Space  → C (patch / toggle)
    Tab / f       → D (focus cycle)
    r             → refresh graph (extra)
    1 / 2 / 3     → switch screen (splash / status / patchbay) when supported
    q / Ctrl+C    → quit
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import TextIO

from .buttons import BUTTONS, LABELS, ButtonEvent, ButtonReader


@dataclass
class InputEvent:
    """Normalized UI action."""

    action: str  # up|down|patch|focus|refresh|quit|screen_splash|screen_status|screen_patchbay
    source: str  # button|keyboard
    raw: str = ""


_KEY_MAP = {
    # arrows (CSI) handled separately
    "k": "up",
    "w": "up",
    "a": "up",  # also physical A
    "j": "down",
    "s": "down",
    "b": "down",
    "\r": "patch",
    "\n": "patch",
    " ": "patch",
    "c": "patch",
    "\t": "focus",
    "f": "focus",
    "d": "focus",
    "r": "refresh",
    "q": "quit",
    "1": "screen_splash",
    "2": "screen_status",
    "3": "screen_patchbay",
}

_BUTTON_TO_ACTION = {
    "A": "up",
    "B": "down",
    "C": "patch",
    "D": "focus",
}


class KeyboardReader:
    """Non-blocking single-key reader for a TTY (SSH / local console)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdin
        self._fd: int | None = None
        self._old: list | None = None
        self.enabled = False
        try:
            if self.stream.isatty():
                self._fd = self.stream.fileno()
                self._old = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
                self.enabled = True
        except (termios.error, OSError, ValueError) as exc:
            print(f"[input] keyboard disabled ({exc})", file=sys.stderr)
            self.enabled = False

    def poll(self) -> InputEvent | None:
        if not self.enabled or self._fd is None:
            return None
        try:
            ready, _, _ = select.select([self._fd], [], [], 0)
            if not ready:
                return None
            ch = os_read_char(self._fd)
            if not ch:
                return None
            # Escape sequences: arrows
            if ch == "\x1b":
                # drain rest of CSI if present
                seq = ch
                for _ in range(3):
                    r, _, _ = select.select([self._fd], [], [], 0.02)
                    if not r:
                        break
                    seq += os_read_char(self._fd)
                if seq in ("\x1b[A", "\x1bOA"):
                    return InputEvent("up", "keyboard", seq)
                if seq in ("\x1b[B", "\x1bOB"):
                    return InputEvent("down", "keyboard", seq)
                if seq in ("\x1b[C", "\x1bOC"):
                    return InputEvent("focus", "keyboard", seq)
                if seq in ("\x1b[D", "\x1bOD"):
                    return InputEvent("focus", "keyboard", seq)
                return None
            if ch == "\x03":  # Ctrl+C
                return InputEvent("quit", "keyboard", ch)
            action = _KEY_MAP.get(ch.lower() if len(ch) == 1 and ch.isalpha() else ch)
            if action:
                return InputEvent(action, "keyboard", ch)
        except (OSError, ValueError):
            return None
        return None

    def close(self) -> None:
        if self._fd is not None and self._old is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except termios.error:
                pass
        self.enabled = False


def os_read_char(fd: int) -> str:
    import os

    data = os.read(fd, 1)
    return data.decode("utf-8", errors="ignore") if data else ""


class InputHub:
    """Merge GPIO buttons + keyboard into InputEvents."""

    def __init__(self, simulate_buttons: bool = False) -> None:
        self.buttons = ButtonReader(simulate=simulate_buttons)
        self.keyboard = KeyboardReader()

    def wait(self, timeout_s: float = 0.15) -> InputEvent | None:
        deadline = time.time() + max(0.0, timeout_s)
        while True:
            kev = self.keyboard.poll()
            if kev is not None:
                return kev
            remaining = deadline - time.time()
            if remaining <= 0:
                # one last short button poll
                bev = self.buttons.wait(timeout_s=0)
                if bev is not None:
                    return _button_event(bev)
                return None
            # Poll buttons with a short slice so keyboard stays responsive
            slice_s = min(0.05, remaining)
            bev = self.buttons.wait(timeout_s=slice_s)
            if bev is not None:
                return _button_event(bev)

    def close(self) -> None:
        self.buttons.close()
        self.keyboard.close()


def _button_event(bev: ButtonEvent) -> InputEvent:
    action = _BUTTON_TO_ACTION.get(bev.label, "focus")
    return InputEvent(action, "button", bev.label)


HELP_TEXT = """
Controls (keyboard + Inky side buttons)
  up     ↑  k w a    |  button A
  down   ↓  j s b    |  button B
  patch  Enter Space c |  button C
  focus  Tab f d     |  button D
  refresh  r
  quit     q  Ctrl+C
  screens  1 splash · 2 status · 3 patchbay  (TUI mode)
""".strip()
