"""SEEDS — capture what the piece is, and walk its history.

Eight seed pads (tap recalls, hold captures — the family's scene-pad
mechanics) and the timeline: a strip of the last 32 recorded states with
back/forward steppers and a LIVE key. "Do the thing you did two minutes
ago" is a button here, which is the whole reason the timeline exists.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.seeds import SLOTS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, grid, lcd, row, \
    section_head

STEPPED = ("tlback", "tlfwd")


class SeedsScreen(Screen):
    title = "SEEDS"
    legend = "TAP a seed to recall it · HOLD a seed to save over it"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        if key.startswith("seed"):
            return [cmd.RecallSeed(slot=int(key[4:]))]
        if key == "tlback":
            return [cmd.TimelineStep(delta=-1)]
        if key == "tlfwd":
            return [cmd.TimelineStep(delta=+1)]
        if key == "tllive":
            return [cmd.TimelineLive()]
        if key == "reseed":
            return [cmd.Reseed()]
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("seed"):
            self.host.message(f"SEED {int(key[4:]) + 1} SAVED")
            return [cmd.CaptureSeed(slot=int(key[4:]))]
        return self.on_tap(key)

    def repeats(self, key: str) -> bool:
        return key in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            pads_col, timeline_col = row(inner, 2, gap=10)
        else:
            pads_col, timeline_col = column(inner, 2, gap=8)
        self._pads(surface, pads_col, s)
        self._timeline(surface, timeline_col, s)

    def _pads(self, surface, rect, s) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "SEEDS · TAP RECALL · HOLD CAPTURE")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        pads = grid(body, 2, SLOTS // 2, gap=6)
        for slot, pad in enumerate(pads):
            used = s.seeds_occupied[slot]
            button(surface, self.hits, f"seed{slot}", pad,
                   f"S{slot + 1}", 16,
                   pressed=self.is_pressed(f"seed{slot}"),
                   color=theme.ACCENT if used else None,
                   sub="" if used else "empty")

    def _timeline(self, surface, rect, s) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "TIMELINE · THE LAST 32 STATES")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        cells = column(body, 3, gap=6)
        # The strip: one tick per recorded state, the restored one lit.
        strip = cells[0]
        surface.fill(theme.BG_SUNKEN, strip)
        count = max(1, s.timeline_len)
        position = s.timeline_pos if s.timeline_pos >= 0 \
            else s.timeline_len - 1
        for index in range(s.timeline_len):
            x = strip.x + index * strip.width // count
            width = max(2, strip.width // count - 2)
            cell = pygame.Rect(x + 1, strip.y + 4, width, strip.height - 8)
            here = index == position
            surface.fill(theme.ACCENT2 if here else theme.ACCENT, cell)
        pygame.draw.rect(surface, theme.BORDER, strip, 1)
        steppers = row(cells[1], 3, gap=5)
        button(surface, self.hits, "tlback", steppers[0], "◀", 18,
               pressed=self.is_pressed("tlback"))
        button(surface, self.hits, "tllive", steppers[1],
               "LIVE" if s.timeline_pos >= 0 else "●", 14,
               active=s.timeline_pos < 0, color=theme.ACCENT)
        button(surface, self.hits, "tlfwd", steppers[2], "▶", 18,
               pressed=self.is_pressed("tlfwd"))
        bottom = row(cells[2], 2, gap=5)
        lcd(surface, bottom[0],
            f"{s.timeline_len}", size=16,
            label="STATES" if s.timeline_pos < 0
            else f"AT {position + 1}/{s.timeline_len}")
        button(surface, self.hits, "reseed", bottom[1], "RESEED ALL", 12,
               color=theme.ACCENT2)
