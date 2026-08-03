"""ARRANGE — the scene chain, written down.

Append scenes with their bar counts, then flip the chain on and the set
plays itself — every launch still going through the quantized path a
finger would use. Tap an entry to remove it; the running entry is lit.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.grid import SCENES
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, lcd, row, \
    section_head, text

STEPPED = ("bars",)


class ArrangeScreen(Screen):
    title = "ARRANGE"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._bars = 4

    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key == "chain":
            return [cmd.SetChainOn(on=not s.chain_on)]
        if key == "clearchain":
            return [cmd.ChainClear()]
        if key.startswith("add"):
            return [cmd.ChainAppend(scene=int(key[3:]), bars=self._bars)]
        if key.startswith("ent"):
            return [cmd.ChainRemove(position=int(key[3:]))]
        if key.endswith(("+", "-")):
            direction = +1 if key.endswith("+") else -1
            if key[:-1] == "bars":
                self._bars = max(1, min(32, self._bars + direction))
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            build_col, chain_col = row(inner, 2, gap=10)
        else:
            build_col, chain_col = column(inner, 2, gap=8)
        head = pygame.Rect(build_col.x, build_col.y, build_col.width, 18)
        section_head(surface, head, "ADD A SCENE · HOLD FOR ITS BARS")
        body = pygame.Rect(build_col.x, build_col.y + 20, build_col.width,
                           build_col.height - 20)
        cells = column(body, 3, gap=6)
        scene_row = row(cells[0], SCENES, gap=3)
        for scene, cell in enumerate(scene_row):
            button(surface, self.hits, f"add{scene}", cell,
                   f"S{scene + 1}", 12,
                   color=theme.ACCENT2 if s.scenes_filled[scene] else None,
                   pressed=self.is_pressed(f"add{scene}"))
        Stepper("bars", "BARS PER ENTRY", str(self._bars)).draw(
            surface, self.hits, cells[1], self._pressed)
        controls = row(cells[2], 2, gap=5)
        button(surface, self.hits, "chain", controls[0],
               "CHAIN ON" if not s.chain_on else "CHAIN OFF", 13,
               active=s.chain_on, color=theme.ACCENT)
        button(surface, self.hits, "clearchain", controls[1], "CLEAR", 12,
               color=theme.DANGER)

        head = pygame.Rect(chain_col.x, chain_col.y, chain_col.width, 18)
        section_head(surface, head, "THE CHAIN · TAP AN ENTRY TO DROP IT")
        body = pygame.Rect(chain_col.x, chain_col.y + 20, chain_col.width,
                           chain_col.height - 20)
        if not s.chain:
            text(surface, "empty — add scenes on the left", body, 12,
                 theme.TEXT_MUTED)
            return
        entries = column(body, max(4, len(s.chain)), gap=3)
        for position, ((scene, bars), cell) in enumerate(
                zip(s.chain, entries)):
            running = s.chain_on and position == s.chain_position
            button(surface, self.hits, f"ent{position}", cell,
                   f"{position + 1}. S{scene + 1} × {bars} bars", 12,
                   active=running, color=theme.ACCENT, display=False)
        if s.chain_on and s.chain_position >= 0:
            lcd(surface, entries[-1] if len(entries) > len(s.chain)
                else pygame.Rect(body.x, body.bottom - 20, body.width, 18),
                f"AT {s.chain_position + 1}/{len(s.chain)}", size=11,
                label="")
