"""SLICE — a captured phrase, playable.

Sixteen pads chop the source track's loop (slice mode) or spread it across
transpositions (chromatic mode). Tap fires the full velocity layer; a long
press fires the soft one — two layers, no extra chrome. The source selector
is the same track strip order as PERFORM.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.slicer import MODES
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, grid, row, section_head


class SliceScreen(Screen):
    title = "SLICE"
    legend = "TAP a slice to select it · HOLD a slice to fire it"

    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("src"):
            return [cmd.SelectSliceSource(index=int(key[3:]))]
        if key == "mode":
            return [cmd.SetSliceMode(mode=cycle(MODES, s.slice_mode))]
        if key.startswith("pad"):
            return [cmd.FireSlice(pad=int(key[3:]), layer=1.0)]
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("pad"):
            return [cmd.FireSlice(pad=int(key[3:]), layer=0.0)]
        return self.on_tap(key)

    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head,
                     "SLICE · TAP FULL · HOLD SOFT")
        strip_h = max(theme.TOUCH_MIN, inner.height // 6)
        strip = pygame.Rect(inner.x, inner.y + 20, inner.width, strip_h)
        cells = row(strip, len(s.tracks) + 1, gap=4)
        for index, (view, cell) in enumerate(zip(s.tracks, cells)):
            button(surface, self.hits, f"src{index}", cell,
                   f"T{index + 1}", 13,
                   active=index == s.slice_source,
                   color=theme.ACCENT if view.notes else None,
                   sub=str(view.notes) if view.notes else "empty")
        button(surface, self.hits, "mode", cells[-1], s.slice_mode, 12,
               color=theme.ACCENT2, sub="mode")
        pads_rect = pygame.Rect(inner.x, strip.bottom + 6, inner.width,
                                inner.bottom - strip.bottom - 6)
        wide = theme.is_wide(self.rect)
        pads = grid(pads_rect, 8 if wide else 4, 2 if wide else 4, gap=6)
        for pad, cell in enumerate(pads):
            filled = s.slice_filled[pad] if pad < len(s.slice_filled) \
                else False
            button(surface, self.hits, f"pad{pad}", cell,
                   s.slice_captions[pad] if pad < len(s.slice_captions)
                   else "", 16,
                   pressed=self.is_pressed(f"pad{pad}"),
                   color=theme.ACCENT if filled else None,
                   active=filled, display=False)
