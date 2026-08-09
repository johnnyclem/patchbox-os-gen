"""BROWSER — the preset bank, eight names at a time.

Tap a name to load it into the selected part's A patch; with B TARGET
lit the load lands on the morph target instead. SAVE writes the part's
current A patch to the user preset directory under its patch name.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, lcd, row, section_head, \
    text

PAGE = 8


class BrowserScreen(Screen):
    title = "BROWSER"
    legend = "TAP a preset to load it · ◂ / ▸ page through the bank"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._page = 0
        self._to_b = False

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("part"):
            return [cmd.SelectPart(part=int(key[4:]))]
        if key in ("prev", "next"):
            count = len(self.host.presets())
            pages = max(1, (count + PAGE - 1) // PAGE)
            self._page = (self._page + (1 if key == "next" else -1)) \
                % pages
            return []
        if key.startswith("pre"):
            self.host.load_preset_index(self._page * PAGE + int(key[3:]),
                                        self._to_b)
            return []
        if key == "target":
            self._to_b = not self._to_b
            return []
        if key == "save":
            self.host.save_preset()
            return []
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        strip = pygame.Rect(inner.x, inner.y, inner.width,
                            max(theme.TOUCH_MIN, inner.height // 8))
        cells = row(strip, 6, gap=3)
        for index in range(4):
            view = s.parts[index]
            button(surface, self.hits, f"part{index}", cells[index],
                   f"P{index + 1}", 12, active=index == s.selected_part,
                   sub=view.name[:6].lower())
        button(surface, self.hits, "target", cells[4],
               "B TARGET" if self._to_b else "A SLOT", 11,
               active=self._to_b, color=theme.ACCENT2,
               sub="load lands on")
        button(surface, self.hits, "save", cells[5], "SAVE", 12,
               color=theme.ACCENT, sub="A ▸ user bank")
        body = self._titled(surface, pygame.Rect(
            inner.x, strip.bottom + 6, inner.width,
            inner.bottom - strip.bottom - 6),
            "PRESETS · factory + user")
        presets = self.host.presets()
        wide = theme.is_wide(self.rect)
        if wide:
            list_rect, side = row(body, 2, gap=8)
            lines = column(list_rect, PAGE // 2, gap=3)
            cells = []
            for line in lines:
                cells.extend(row(line, 2, gap=3))
        else:
            side = None
            lines = column(body, PAGE + 1, gap=3)
            cells = lines[:PAGE]
        for index, cell in enumerate(cells[:PAGE]):
            at = self._page * PAGE + index
            if at >= len(presets):
                continue
            button(surface, self.hits, f"pre{index}", cell,
                   presets[at].stem.upper()[:14], 12, display=False)
        if not presets:
            text(surface, "no presets found", body, 12, theme.TEXT_MUTED)
        pages = max(1, (len(presets) + PAGE - 1) // PAGE)
        if side is not None:
            rows_ = column(side, 3, gap=4)
            pager = row(rows_[0], 2, gap=4)
            button(surface, self.hits, "prev", pager[0], "◂", 15,
                   sub="page")
            button(surface, self.hits, "next", pager[1], "▸", 15,
                   sub="page")
            lcd(surface, rows_[1], f"{self._page + 1}/{pages}", size=14,
                label="PAGE")
            view = s.parts[s.selected_part]
            lcd(surface, rows_[2], view.name[:10], size=13,
                label=f"P{s.selected_part + 1} A PATCH")
        else:
            pager = row(lines[PAGE], 2, gap=4)
            button(surface, self.hits, "prev", pager[0], "◂", 15,
                   sub=f"{self._page + 1}/{pages}")
            button(surface, self.hits, "next", pager[1], "▸", 15)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)
