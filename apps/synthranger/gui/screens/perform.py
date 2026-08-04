"""PERFORM — two octaves under the fingers, an XY pad under the thumb.

The touch keyboard plays the selected part through the engine's release
book (press sounds, lift releases, a finger sliding off still lifts). The
XY pad drives mod sources ``xy_x``/``xy_y`` — dragging streams positions
while the finger is down. Part keys switch the played part; the morph
stepper leans the sound toward patch B.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.parts import PARTS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, lcd, panel, row, text
from rangerkit.theory import note_name

BASE_NOTE = 48                   # C3
KEYS = 24
STEPPED = ("morph", "oct")


class PerformScreen(Screen):
    title = "PERFORM"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._octave = 0
        self._xy_rect: pygame.Rect | None = None
        self._last_pos = (0, 0)

    # --- input ----------------------------------------------------------------
    def handle(self, event: pygame.event.Event) -> list:
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION):
            self._last_pos = event.pos
        if event.type == pygame.MOUSEMOTION and self._pressed == "xy":
            return self._xy_command(event.pos)
        return super().handle(event)

    def _xy_command(self, pos) -> list:
        rect = self._xy_rect
        if rect is None or rect.width <= 1 or rect.height <= 1:
            return []
        x = (pos[0] - rect.x) / rect.width
        y = 1.0 - (pos[1] - rect.y) / rect.height
        return [cmd.SetXY(x=max(0.0, min(1.0, x)),
                          y=max(0.0, min(1.0, y)))]

    def on_press(self, key: str) -> list:
        if key.startswith("k"):
            return [cmd.KeyDown(note=self._note(int(key[1:])))]
        if key == "xy":
            return self._xy_command(self._last_pos)
        return []

    def on_release(self, key: str, moved_away: bool = False) -> list:
        if key.startswith("k"):
            return [cmd.KeyUp(note=self._note(int(key[1:])))]
        return []

    def on_tap(self, key: str) -> list:
        if key.startswith("part"):
            return [cmd.SelectPart(part=int(key[4:]))]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _note(self, index: int) -> int:
        return BASE_NOTE + self._octave * 12 + index

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        if name == "oct":
            self._octave = max(-2, min(3, self._octave + direction))
            return []
        if name == "morph" and s is not None:
            part = s.parts[s.selected_part]
            return [cmd.SetPartField(
                part=s.selected_part, name="morph",
                value=round(part.morph + 0.05 * direction, 3))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        wide = theme.is_wide(self.rect)
        if wide:
            keys_rect = pygame.Rect(inner.x, inner.y,
                                    inner.width * 3 // 5, inner.height)
            rail = pygame.Rect(keys_rect.right + 6, inner.y,
                               inner.right - keys_rect.right - 6,
                               inner.height)
        else:
            keys_rect = pygame.Rect(inner.x, inner.y, inner.width,
                                    inner.height * 11 // 20)
            rail = pygame.Rect(inner.x, keys_rect.bottom + 6, inner.width,
                               inner.bottom - keys_rect.bottom - 6)
        self._keys(surface, keys_rect, s)
        self._rail(surface, rail, s)

    def _keys(self, surface, rect, s) -> None:
        held = set(s.held_notes)
        for index, cell in enumerate(row(rect, KEYS, gap=1)):
            note = self._note(index)
            name = note_name(note)
            black = "#" in name
            key = f"k{index}"
            face = theme.ACCENT if note in held else (
                theme.BG_SUNKEN if black else theme.BG_RAISED)
            panel(surface, cell, face)
            self.hits.add(key, cell)
            label = name if note % 12 == 0 or not black else name
            text(surface, label,
                 pygame.Rect(cell.x, cell.bottom - 22, cell.width, 18),
                 9, theme.ink_for(face), display=True)

    def _rail(self, surface, rect, s) -> None:
        from rangerkit.gui.widgets import column
        rows = column(rect, 4, gap=5)
        cells = row(rows[0], PARTS, gap=3)
        for index, cell in enumerate(cells):
            view = s.parts[index]
            button(surface, self.hits, f"part{index}", cell,
                   f"P{index + 1}", 13,
                   active=index == s.selected_part,
                   color=theme.DANGER if view.muted else
                   (theme.ACCENT if view.sounding else None),
                   sub=view.engine)
        # The XY pad.
        pad = rows[1].union(rows[2])
        panel(surface, pad, theme.BG_SUNKEN)
        self.hits.add("xy", pad)
        self._xy_rect = pad
        x = pad.x + int(s.xy[0] * max(1, pad.width))
        y = pad.y + int((1.0 - s.xy[1]) * max(1, pad.height))
        pygame.draw.circle(surface, theme.ACCENT2, (x, y), 9)
        text(surface, "XY · mod matrix",
             pygame.Rect(pad.x + 6, pad.y + 4, pad.width - 12, 14), 10,
             theme.TEXT_DIM, align="left", display=True)
        bottom = row(rows[3], 3, gap=4)
        Stepper("oct", "OCT", f"{self._octave:+d}", width=30).draw(
            surface, self.hits, bottom[0], self._pressed, size=13)
        part = s.parts[s.selected_part]
        Stepper("morph", "MORPH", f"{part.morph:.0%}", width=30).draw(
            surface, self.hits, bottom[1], self._pressed, size=13)
        lcd(surface, bottom[2], part.name[:8], size=13,
            label=f"A ▸ {part.name_b[:6]}")
