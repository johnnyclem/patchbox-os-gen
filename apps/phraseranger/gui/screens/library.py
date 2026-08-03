"""LIBRARY — scenes of the whole desk, and the project file.

Eight scene pads (tap recalls, hold saves — the family's pad mechanics)
holding complete track states, plus save/new for the project.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.scene import SLOTS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, grid, lcd, row, \
    section_head


class LibraryScreen(Screen):
    title = "LIBRARY"

    def on_tap(self, key: str) -> list:
        if key.startswith("scene"):
            return [cmd.RecallScene(slot=int(key[5:]))]
        if key == "save":
            self.host.save_project()
            return []
        if key == "new":
            self.host.new_project()
            return []
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("scene"):
            self.host.message(f"SCENE {int(key[5:]) + 1} SAVED")
            return [cmd.SaveScene(slot=int(key[5:]))]
        return self.on_tap(key)

    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            scenes_col, file_col = row(inner, 2, gap=10)
        else:
            scenes_col, file_col = column(inner, 2, gap=8)
        head = pygame.Rect(scenes_col.x, scenes_col.y, scenes_col.width, 18)
        section_head(surface, head, "SCENES · TAP RECALL · HOLD SAVE")
        body = pygame.Rect(scenes_col.x, scenes_col.y + 20, scenes_col.width,
                           scenes_col.height - 20)
        for slot, pad in enumerate(grid(body, 2, SLOTS // 2, gap=6)):
            used = s.scenes_occupied[slot]
            button(surface, self.hits, f"scene{slot}", pad,
                   f"S{slot + 1}", 16,
                   pressed=self.is_pressed(f"scene{slot}"),
                   color=theme.ACCENT if used else None,
                   sub="" if used else "empty")
        head = pygame.Rect(file_col.x, file_col.y, file_col.width, 18)
        section_head(surface, head, "PROJECT")
        body = pygame.Rect(file_col.x, file_col.y + 20, file_col.width,
                           file_col.height - 20)
        cells = column(body, 3, gap=6)
        lcd(surface, cells[0], s.project_name[:14], size=15,
            label="PROJECT")
        files = row(cells[1], 2, gap=5)
        button(surface, self.hits, "save", files[0], "SAVE", 14,
               color=theme.ACCENT)
        button(surface, self.hits, "new", files[1], "NEW", 14)
        takes = sum(view.notes for view in s.tracks)
        lcd(surface, cells[2], str(takes), size=16, label="NOTES HELD")
