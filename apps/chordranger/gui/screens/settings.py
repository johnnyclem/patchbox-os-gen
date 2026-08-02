"""SET — I/O, files and everything that is not playing.

Four columns: the MIDI output and what it is bound to, the chordset and style
browsers, the project browser, and the panel's own options. The MIDI column
comes first and says what backend is in force, because "why can I not hear
anything" is the question this screen exists to answer, and the answer is
nearly always on the left of it.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.theory import SCALE_NAMES, SCALES, note_name
from gui import theme
from gui.screens.base import Screen
from gui.widgets import Stepper, button, column, lcd, panel, row, text

LIST_ROWS = 5


class SettingsScreen(Screen):
    title = "SET"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self.port_page = 0
        self.set_page = 0
        self.style_page = 0

    # --- input ---------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        snapshot = self.snapshot
        if key == "portpage":
            ports = self.host.midi_ports()
            self.port_page = (self.port_page + LIST_ROWS) % max(1, len(ports))
            return []
        if key.startswith("port"):
            ports = self.host.midi_ports()
            index = self.port_page + int(key[4:])
            if index < len(ports):
                self.host.bind_output(ports[index])
            return []
        if key == "setpage":
            self.set_page = (self.set_page + 3) % max(
                1, len(self.host.chordsets()))
            return []
        if key == "stylepage":
            self.style_page = (self.style_page + 3) % max(
                1, len(self.host.styles()))
            return []
        if key.startswith("set:"):
            self.host.load_chordset(int(key.split(":", 1)[1]))
            return []
        if key.startswith("style:"):
            self.host.load_style(int(key.split(":", 1)[1]))
            return []
        if key.startswith("proj:"):
            self.host.load_project(int(key.split(":", 1)[1]))
            return []
        if key == "save":
            self.host.save_project()
            return []
        if key == "new":
            self.host.new_project()
            return []
        if key == "saveset":
            self.host.save_chordset()
            return []
        if key == "theme":
            self.host.cycle_theme()
            return []
        if key == "clock":
            return [cmd.SetClockOut(not (snapshot.clock_out if snapshot
                                         else False))]
        if key == "metro":
            return [cmd.SetMetronome(not (snapshot.metronome if snapshot
                                          else False))]
        if key in ("key-", "key+"):
            step = 1 if key.endswith("+") else -1
            return [cmd.TransposeChordset(step)]
        if key in ("scale-", "scale+"):
            step = 1 if key.endswith("+") else -1
            names = SCALE_NAMES
            here = names.index(snapshot.scale) if snapshot \
                and snapshot.scale in names else 0
            return [cmd.SetKey(snapshot.key_root if snapshot else 0,
                               names[(here + step) % len(names)])]
        if key == "panic":
            return [cmd.Panic()]
        return []

    # --- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        surface.fill(theme.BG, self.rect)
        columns = row(self.rect, 4, gap=6)
        self._draw_midi(surface, columns[0])
        self._draw_library(surface, columns[1])
        self._draw_projects(surface, columns[2])
        self._draw_panel(surface, columns[3])

    def _head(self, surface, rect, label) -> pygame.Rect:
        head = pygame.Rect(rect.x, rect.y, rect.width, 16)
        text(surface, label, head, 11, theme.TEXT_DIM, display=True,
             align="left", pad=2)
        return pygame.Rect(rect.x, head.bottom, rect.width,
                           rect.height - head.height)

    def _draw_midi(self, surface, rect) -> None:
        snapshot = self.snapshot
        body = self._head(surface, rect, "MIDI OUT")
        cells = column(body, 7, gap=3)
        backend = snapshot.backend if snapshot else "null"
        bound = bool(snapshot and snapshot.output_bound)
        lcd(surface, cells[0], backend.upper(),
            size=18, label="BACKEND",
            color=theme.DISPLAY if bound else theme.WARN)
        ports = self.host.midi_ports()
        for slot in range(LIST_ROWS):
            index = self.port_page + slot
            cell = cells[1 + slot]
            if index >= len(ports):
                panel(surface, cell, theme.BG_SUNKEN)
                continue
            name = ports[index]
            button(surface, self.hits, f"port{slot}", cell, name[:18], 12,
                   display=False, color=theme.ACCENT3)
        button(surface, self.hits, "portpage", cells[6],
               f"MORE ({len(ports)})", 11, color=theme.ACCENT3)

    def _draw_library(self, surface, rect) -> None:
        """Chordsets over styles, three of each with their own paging.

        Three rows each is what the column height allows at a 44 px target,
        and there are more than three of both — so each list gets a page
        button rather than quietly hiding everything past the third entry.
        """
        body = self._head(surface, rect, "CHORDSETS · STYLES")
        cells = column(body, 7, gap=3)
        sets = self.host.chordsets()
        for slot in range(3):
            index = (self.set_page + slot) % max(1, len(sets))
            cell = cells[slot]
            if slot >= len(sets):
                panel(surface, cell, theme.BG_SUNKEN)
                continue
            active = bool(self.snapshot
                          and self.snapshot.chordset_name == sets[index])
            button(surface, self.hits, f"set:{index}", cell, sets[index][:16],
                   12, active=active, color=theme.ACCENT, display=False)
        styles = self.host.styles()
        for slot in range(3):
            index = (self.style_page + slot) % max(1, len(styles))
            cell = cells[3 + slot]
            if slot >= len(styles):
                panel(surface, cell, theme.BG_SUNKEN)
                continue
            active = bool(self.snapshot
                          and self.snapshot.style_name == styles[index])
            button(surface, self.hits, f"style:{index}", cell, styles[index],
                   12, active=active, color=theme.ACCENT2, display=False)
        actions = row(cells[6], 3, gap=4)
        button(surface, self.hits, "setpage", actions[0], f"SET {len(sets)}",
               11, color=theme.ACCENT3)
        button(surface, self.hits, "stylepage", actions[1],
               f"STY {len(styles)}", 11, color=theme.ACCENT3)
        button(surface, self.hits, "saveset", actions[2], "SAVE", 11,
               color=theme.ACCENT3)

    def _draw_projects(self, surface, rect) -> None:
        body = self._head(surface, rect, "PROJECTS")
        cells = column(body, 7, gap=3)
        projects = self.host.projects()
        for slot in range(LIST_ROWS):
            cell = cells[slot]
            if slot >= len(projects):
                panel(surface, cell, theme.BG_SUNKEN)
                continue
            button(surface, self.hits, f"proj:{slot}", cell,
                   projects[slot][:18], 12, color=theme.ACCENT3,
                   display=False)
        actions = row(cells[5], 2, gap=4)
        button(surface, self.hits, "save", actions[0], "SAVE", 13,
               color=theme.ACCENT2, pressed=self.is_pressed("save"))
        button(surface, self.hits, "new", actions[1], "NEW", 13,
               color=theme.ACCENT3, pressed=self.is_pressed("new"))
        button(surface, self.hits, "panic", cells[6], "PANIC", 13,
               color=theme.DANGER, pressed=self.is_pressed("panic"),
               sub="ALL NOTES OFF")

    def _draw_panel(self, surface, rect) -> None:
        snapshot = self.snapshot
        body = self._head(surface, rect, "PANEL")
        cells = column(body, 7, gap=3)
        Stepper("key", "KEY",
                note_name(snapshot.key_root) if snapshot else "C",
                width=30).draw(surface, self.hits, cells[0], self._pressed,
                               size=14)
        scale_label = (SCALES[snapshot.scale].label
                       if snapshot and snapshot.scale in SCALES else "MAJOR")
        Stepper("scale", "SCALE", scale_label, width=30).draw(
            surface, self.hits, cells[1], self._pressed, size=12)
        button(surface, self.hits, "metro", cells[2], "METRONOME", 12,
               active=bool(snapshot and snapshot.metronome),
               color=theme.ACCENT3)
        button(surface, self.hits, "clock", cells[3], "CLOCK OUT", 12,
               active=bool(snapshot and snapshot.clock_out),
               color=theme.ACCENT3)
        button(surface, self.hits, "theme", cells[4],
               theme.COLORWAYS[theme.active()].label, 12,
               color=theme.ACCENT3)
        from core.version import __version__
        text(surface, f"CHORDRANGER {__version__}", cells[5], 11,
             theme.TEXT_DIM, display=True)
        voices = snapshot.voices if snapshot else 0
        text(surface, f"VOICES {voices}", cells[6], 11, theme.TEXT_DIM,
             display=True)
