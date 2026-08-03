"""SONG — the chain that presses the pattern buttons, and the master bus.

Top: the chain entries (tap one to remove it), the add row (pattern +
passes + ADD), and the ON switch. Bottom: the master bus — one-knob
filter, delay division, reverb return, master level — the engine keeps the
sampler's copy true over the internal CC contract.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.fxbus import DELAY_DIVISIONS
from core.sequencer import PATTERNS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, \
    section_head, text

STEPPED = ("addpt", "addps", "mfilt", "mdiv", "mverb", "mlvl")
ENTRIES_SHOWN = 8
_DIV_NAMES = ("1/8", ".1/8", "1/4", "1/2")


class SongScreen(Screen):
    title = "SONG"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._pattern = 0
        self._passes = 4

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("en"):
            return [cmd.ChainRemove(position=int(key[2:]))]
        if key == "add":
            return [cmd.ChainAppend(pattern=self._pattern,
                                    passes=self._passes)]
        if key == "on":
            return [cmd.SetChainOn(on=not s.chain_on)]
        if key == "wipe":
            return [cmd.ChainClear()]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        if name == "addpt":
            self._pattern = (self._pattern + direction) % PATTERNS
            return []
        if name == "addps":
            self._passes = max(1, min(64, self._passes + direction))
            return []
        if name == "mfilt":
            return [cmd.SetMasterField(
                name="filter",
                value=round(s.mixer.filter + 0.05 * direction, 3))]
        if name == "mdiv":
            return [cmd.SetMasterField(
                name="delay_div",
                value=(s.mixer.delay_div + direction)
                % len(DELAY_DIVISIONS))]
        if name == "mverb":
            return [cmd.SetMasterField(
                name="reverb",
                value=round(s.mixer.reverb + 0.05 * direction, 3))]
        if name == "mlvl":
            return [cmd.SetMasterField(
                name="master",
                value=round(s.mixer.master + 0.05 * direction, 3))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        halves = row(inner, 2, gap=10) if theme.is_wide(self.rect) \
            else column(inner, 2, gap=6)
        self._chain(surface, halves[0], s)
        self._bus(surface, halves[1], s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)

    def _chain(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "SONG CHAIN")
        lines = column(body, 3, gap=4)
        cells = row(lines[0], ENTRIES_SHOWN, gap=3)
        if not s.chain:
            text(surface, "empty — add entries below", lines[0], 12,
                 theme.TEXT_MUTED)
        for index, cell in enumerate(cells):
            if index >= len(s.chain):
                continue
            pattern, passes = s.chain[index]
            here = s.chain_on and index == s.chain_position
            button(surface, self.hits, f"en{index}", cell,
                   f"P{pattern + 1}", 13, active=here,
                   color=theme.ACCENT if here else theme.ACCENT2,
                   sub=f"×{passes}")
        add = row(lines[1], 3, gap=4)
        Stepper("addpt", "PATTERN", f"P{self._pattern + 1}",
                width=32).draw(surface, self.hits, add[0], self._pressed,
                               size=12)
        Stepper("addps", "PASSES", f"×{self._passes}", width=32).draw(
            surface, self.hits, add[1], self._pressed, size=12)
        button(surface, self.hits, "add", add[2], "ADD", 14,
               color=theme.ACCENT2)
        controls = row(lines[2], 2, gap=4)
        button(surface, self.hits, "on", controls[0],
               "SONG ON" if s.chain_on else "SONG OFF", 14,
               active=s.chain_on, color=theme.ACCENT,
               sub=f"entry {s.chain_position + 1}/{len(s.chain)}"
               if s.chain_on and s.chain else "chain idle")
        button(surface, self.hits, "wipe", controls[1], "CLEAR", 13,
               color=theme.DANGER, sub="whole chain")

    def _bus(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "MASTER BUS · internal DAC")
        lines = column(body, 2, gap=5)
        top = row(lines[0], 2, gap=4)
        Stepper("mfilt", "FILTER",
                "OPEN" if 0.45 <= s.mixer.filter <= 0.55 else
                f"{s.mixer.filter:.2f}", width=36).draw(
            surface, self.hits, top[0], self._pressed, size=13)
        Stepper("mdiv", "DELAY", _DIV_NAMES[s.mixer.delay_div],
                width=36).draw(surface, self.hits, top[1], self._pressed,
                               size=13)
        bottom = row(lines[1], 2, gap=4)
        Stepper("mverb", "REVERB", f"{s.mixer.reverb:.2f}",
                width=36).draw(surface, self.hits, bottom[0],
                               self._pressed, size=13)
        Stepper("mlvl", "MASTER", f"{s.mixer.master:.2f}",
                width=36).draw(surface, self.hits, bottom[1],
                               self._pressed, size=13)
