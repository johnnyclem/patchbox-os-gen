"""SONG — the chord track.

Sixteen bar cells across the panel, each showing the chord in force and any
section marker on it. Tapping a bar selects it; tapping a pad on PERFORM while
RECORD is armed writes there. That division is deliberate: entering a
progression is a *performance*, done on the pads with the transport running,
and this screen is for looking at the result and fixing the bar you fluffed.

Only the chord changes are stored (``core.song``), so what you see here is the
whole arrangement — there is no hidden note data to get out of step with it.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.song import ChordStep, Song
from core.style import SECTION_LABELS, SECTION_ORDER
from gui import theme
from gui.screens.base import Screen
from gui.widgets import Stepper, button, grid, panel, row, text

VISIBLE_BARS = 16


class SongScreen(Screen):
    title = "SONG"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self.cursor = 0                 # selected bar
        self.page = 0                   # first visible bar
        self._section_pick = 0

    # --- input ---------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        snapshot = self.snapshot
        if key.startswith("bar"):
            self.cursor = self.page + int(key[3:])
            return []
        if key == "rec":
            return [cmd.SetRecord(not (snapshot.recording if snapshot
                                       else False))]
        if key == "songmode":
            return [cmd.SetSongMode(not (snapshot.song_mode if snapshot
                                         else False))]
        if key == "write":
            chord = snapshot.chord if snapshot else None
            if chord is None:
                self.host.message("NO CHORD HELD")
                return []
            self.host.message(f"BAR {self.cursor + 1} = {chord.symbol()}")
            return [cmd.WriteChordStep(ChordStep(bar=self.cursor, beat=0,
                                                 chord=chord))]
        if key == "erase":
            return [cmd.EraseChordStep(self.cursor, 0)]
        if key == "mark":
            section = SECTION_ORDER[self._section_pick]
            chord = self._chord_at(self.cursor)
            if chord is None:
                self.host.message("WRITE A CHORD FIRST")
                return []
            return [cmd.WriteChordStep(ChordStep(bar=self.cursor, beat=0,
                                                 chord=chord,
                                                 section=section))]
        if key in ("sect-", "sect+"):
            step = 1 if key.endswith("+") else -1
            self._section_pick = (self._section_pick + step) % len(
                SECTION_ORDER)
            return []
        if key in ("cur-", "cur+"):
            step = 1 if key.endswith("+") else -1
            self.cursor = max(0, self.cursor + step)
            self._follow_cursor()
            return []
        if key == "locate":
            return [cmd.Locate(self.cursor)]
        if key == "clear":
            self.host.message("SONG CLEARED")
            return [cmd.SetSong(Song(name=self.snapshot.song_name
                                     if self.snapshot else "SONG"))]
        return []

    def repeats(self, key: str) -> bool:
        return key in ("cur-", "cur+")

    def on_repeat(self, key: str, steps: int) -> list:
        for _ in range(steps):
            self.on_tap(key)
        return []

    def _follow_cursor(self) -> None:
        if self.cursor < self.page:
            self.page = self.cursor
        elif self.cursor >= self.page + VISIBLE_BARS:
            self.page = self.cursor - VISIBLE_BARS + 1

    def _chord_at(self, bar: int):
        """What is playing in *bar*. The screen does not hold the song — it
        reads the snapshot's flattened bar list, which the engine publishes
        precisely so a screen never needs a reference to mutable state."""
        cells = self._bar_cells()
        return cells[bar][0] if 0 <= bar < len(cells) else None

    def _bar_cells(self):
        snapshot = self.snapshot
        return snapshot.song_bars_view if snapshot else ()

    # --- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        snapshot = self.snapshot
        surface.fill(theme.BG, self.rect)
        head = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, 20)
        text(surface,
             f"SONG — {snapshot.song_name if snapshot else ''}   "
             f"BAR {self.cursor + 1}", head, 11, theme.TEXT_DIM, display=True,
             align="left", pad=2)
        grid_rect = pygame.Rect(self.rect.x, head.bottom, self.rect.width,
                                self.rect.height - head.height - 64)
        controls = pygame.Rect(self.rect.x, grid_rect.bottom + 4,
                               self.rect.width,
                               self.rect.bottom - grid_rect.bottom - 6)
        self._draw_grid(surface, grid_rect, snapshot)
        self._draw_controls(surface, controls, snapshot)

    def _draw_grid(self, surface, rect, snapshot) -> None:
        cells = grid(rect, VISIBLE_BARS // 2, 2, gap=4)
        bars = self._bar_cells()
        playing_bar = snapshot.song_bar if snapshot else -1
        for slot in range(VISIBLE_BARS):
            bar = self.page + slot
            cell = cells[slot]
            chord, section, change = (bars[bar] if bar < len(bars)
                                      else (None, "", False))
            selected = bar == self.cursor
            live = bool(snapshot and snapshot.song_mode
                        and snapshot.playing and bar == playing_bar)
            face = (theme.ACCENT if live else
                    theme.tint(theme.ACCENT3, 0.24) if selected else
                    theme.BG_RAISED if change else
                    theme.blend(theme.BG_RAISED, theme.BG_SUNKEN, 0.6)
                    if chord is not None else theme.BG_SUNKEN)
            panel(surface, cell, face)
            ink = theme.ink_for(face)
            number = pygame.Rect(cell.x + 3, cell.y + 2, 26, 13)
            text(surface, str(bar + 1), number, 10,
                 ink if (live or selected) else theme.TEXT_MUTED,
                 align="left", pad=2)
            if section:
                marker = pygame.Rect(cell.right - 54, cell.y + 2, 52, 13)
                text(surface, SECTION_LABELS.get(section, section), marker, 9,
                     theme.ACCENT2 if not live else ink, display=True)
            # A bar that inherits its chord draws it as a tie rather than
            # repeating the symbol: sixteen cells all reading "G7" says the
            # song is one chord long, which is the opposite of the truth.
            body = pygame.Rect(cell.x, cell.y + 12, cell.width,
                               cell.height - 14)
            if chord is not None and change:
                text(surface, chord.symbol(), body, 22, ink, bold=True)
            elif chord is not None:
                text(surface, "‧ ‧ ‧", body, 18,
                     ink if (live or selected) else theme.TEXT_MUTED)
            else:
                text(surface, "·", body, 18, theme.TEXT_MUTED)
            self.hits.add(f"bar{slot}", cell)

    def _draw_controls(self, surface, rect, snapshot) -> None:
        cells = row(rect, 8, gap=5)
        recording = bool(snapshot and snapshot.recording)
        button(surface, self.hits, "rec", cells[0], "REC", 14,
               active=recording, color=theme.ACCENT2,
               sub="ARMED" if recording else "OFF")
        song_mode = bool(snapshot and snapshot.song_mode)
        button(surface, self.hits, "songmode", cells[1], "SONG", 14,
               active=song_mode, color=theme.ACCENT,
               sub="PLAY" if song_mode else "LIVE")
        button(surface, self.hits, "write", cells[2], "WRITE", 14,
               color=theme.ACCENT3, pressed=self.is_pressed("write"),
               sub="HELD CHORD")
        button(surface, self.hits, "erase", cells[3], "ERASE", 14,
               color=theme.DANGER, pressed=self.is_pressed("erase"))
        Stepper("cur", "BAR", str(self.cursor + 1), width=30).draw(
            surface, self.hits, cells[4], self._pressed, size=14)
        Stepper("sect", "MARK",
                SECTION_LABELS[SECTION_ORDER[self._section_pick]],
                width=26).draw(surface, self.hits, cells[5], self._pressed,
                               size=11)
        button(surface, self.hits, "mark", cells[6], "SET MARK", 12,
               color=theme.ACCENT3, pressed=self.is_pressed("mark"))
        button(surface, self.hits, "locate", cells[7], "LOCATE", 12,
               color=theme.ACCENT3, pressed=self.is_pressed("locate"))
