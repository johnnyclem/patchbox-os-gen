"""PERFORM — the session grid, the wide bar's whole reason to be wide.

Twelve track columns × eight scene rows of clip cells, a scene-launch
column, and stop keys under every track. Tap a filled cell to queue it
(the launch-quantize boundary resolves it); tap it while it plays to queue
its stop; hold an empty cell to arm it for recording. The portrait panel
pages six tracks at a time so every cell keeps its 44 px.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.grid import SCENES, TRACKS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, panel, text

SCENE_W = 64                    # the scene-launch column
STOP_H = 34


class PerformScreen(Screen):
    title = "PERFORM"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._page = 0

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key == "page":
            self._page ^= 1
            return []
        if key.startswith("sc"):
            return [cmd.LaunchScene(scene=int(key[2:]))]
        if key.startswith("st"):
            return [cmd.StopTrack(track=int(key[2:]))]
        if key.startswith("c:"):
            _tag, track, scene = key.split(":")
            track, scene = int(track), int(scene)
            view = s.slots[track][scene]
            if view.armed:
                return [cmd.Disarm()]
            if view.playing:
                return [cmd.StopTrack(track=track)]
            if view.filled:
                return [cmd.LaunchClip(track=track, scene=scene)]
            return []                       # empty pad: a no-op on tap
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("c:"):
            _tag, track, scene = key.split(":")
            s = self.snapshot
            view = s.slots[int(track)][int(scene)]
            if view.armed:
                return [cmd.Disarm()]
            return [cmd.ArmSlot(track=int(track), scene=int(scene))]
        return self.on_tap(key)

    # --- drawing ---------------------------------------------------------------
    def _visible_tracks(self) -> tuple[range, bool]:
        if theme.is_wide(self.rect):
            return range(TRACKS), False
        half = TRACKS // 2
        return range(self._page * half, (self._page + 1) * half), True

    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        tracks, paged = self._visible_tracks()
        grid_rect = pygame.Rect(inner.x + SCENE_W + 4, inner.y,
                                inner.width - SCENE_W - 4,
                                inner.height - STOP_H - 4)
        columns = len(tracks)
        rows = SCENES
        # The scene column.
        for scene in range(rows):
            y = inner.y + scene * grid_rect.height // rows
            height = inner.y + (scene + 1) * grid_rect.height // rows - y
            cell = pygame.Rect(inner.x, y + 1, SCENE_W - 2, height - 3)
            filled = s.scenes_filled[scene]
            chained = bool(s.chain) and s.chain_on \
                and s.chain_position >= 0 \
                and s.chain[s.chain_position][0] == scene
            button(surface, self.hits, f"sc{scene}", cell,
                   f"S{scene + 1}", 13, active=chained,
                   color=theme.ACCENT2 if filled else None,
                   pressed=self.is_pressed(f"sc{scene}"))
        # The clip cells.
        for column_index, track in enumerate(tracks):
            x = grid_rect.x + column_index * grid_rect.width // columns
            width = grid_rect.x + (column_index + 1) * grid_rect.width \
                // columns - x
            for scene in range(rows):
                y = grid_rect.y + scene * grid_rect.height // rows
                height = grid_rect.y + (scene + 1) * grid_rect.height \
                    // rows - y
                cell = pygame.Rect(x + 1, y + 1, width - 3, height - 3)
                view = s.slots[track][scene]
                key = f"c:{track}:{scene}"
                if view.armed:
                    face = theme.DANGER
                elif view.playing:
                    face = theme.ACCENT
                elif view.queued:
                    face = theme.tint(theme.ACCENT, 0.5)
                elif view.filled:
                    face = theme.tint(theme.ACCENT2, 0.25)
                else:
                    face = theme.BG_RAISED
                panel(surface, cell, face)
                self.hits.add(key, cell)
                if view.filled:
                    caption = f"{view.bars}b" + \
                        ("" if view.follow == "none" else "→")
                    text(surface, caption, cell, 10, theme.ink_for(face),
                         display=False)
                elif view.armed:
                    text(surface, "REC", cell, 10, theme.ink_for(face))
            # The stop key under the column.
            stop = pygame.Rect(x + 1, grid_rect.bottom + 3, width - 3,
                               STOP_H)
            strip = s.tracks[track]
            button(surface, self.hits, f"st{track}", stop,
                   f"T{track + 1}" if strip.active < 0 else "■", 11,
                   active=strip.active >= 0, color=theme.ACCENT,
                   sub="" if strip.active < 0 else f"{strip.position:.0%}")
        if paged:
            page = pygame.Rect(inner.x, grid_rect.bottom + 3, SCENE_W - 2,
                               STOP_H)
            button(surface, self.hits, "page", page, "⇄", 14,
                   sub=f"p{self._page + 1}")
