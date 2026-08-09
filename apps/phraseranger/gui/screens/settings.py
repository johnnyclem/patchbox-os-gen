"""SET — ports, clock, pots, file and theme. The screen you visit between
songs, not during one.
"""
from __future__ import annotations

import pygame

from gui.screens.base import Screen
from rangerkit.enginebase import SetClockOut
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, lcd, row, section_head, text
from rangerkit.routing import OUTPUTS

from core.version import APP_NAME, __version__

# PhraseRanger only sends; the bindable endpoints are the outputs.
ENDPOINTS = tuple(o for o in OUTPUTS if o != "internal")
PORTS_SHOWN = 5


class SettingsScreen(Screen):
    title = "SET"
    legend = "TAP a port to bind it · TAP THEME to cycle the colourway"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._endpoint = 0

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if key == "save":
            self.host.save_project()
            return []
        if key == "new":
            self.host.new_project()
            return []
        if key == "theme":
            self.host.cycle_theme()
            return []
        if key == "rescan":
            self.host.refresh_ports()
            self.host.message("PORTS RESCANNED")
            return []
        if key == "clock":
            return [SetClockOut(on=not s.clock_out)] if s else []
        if key == "endpoint":
            self._endpoint = (self._endpoint + 1) % len(ENDPOINTS)
            return []
        if key.startswith("port"):
            ports = self.host.midi_ports()
            index = int(key[4:])
            if index < len(ports):
                self.host.bind_endpoint(ENDPOINTS[self._endpoint],
                                        ports[index])
            return []
        if key in ("learna", "learnb"):
            self.host.learn_pot(0 if key == "learna" else 1)
            return []
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            ports_col, rig_col, file_col = row(inner, 3, gap=10)
        else:
            ports_col, rig_col, file_col = column(inner, 3, gap=8)
        self._ports(surface, ports_col, s)
        self._rig(surface, rig_col, s)
        self._file(surface, file_col, s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 18),
                     label)
        return pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)

    def _ports(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "BIND · ENDPOINT → ALSA PORT")
        cells = column(body, PORTS_SHOWN + 2, gap=4)
        head = row(cells[0], 2, gap=4)
        button(surface, self.hits, "endpoint", head[0],
               ENDPOINTS[self._endpoint].replace("_", " "), 12,
               color=theme.ACCENT, active=True)
        button(surface, self.hits, "rescan", head[1], "RESCAN", 12)
        ports = self.host.midi_ports()
        if not ports:
            text(surface, f"no ports ({s.backend})", cells[1], 12,
                 theme.TEXT_MUTED, align="left")
        for index in range(PORTS_SHOWN):
            cell = cells[1 + index]
            if index >= len(ports):
                continue
            button(surface, self.hits, f"port{index}", cell,
                   ports[index][:24], 11, display=False)
        lcd(surface, cells[-1], s.backend, size=14, label="MIDI BACKEND")

    def _rig(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "CLOCK + POTS")
        cells = column(body, 4, gap=6)
        button(surface, self.hits, "clock", cells[0],
               "CLOCK OUT", 14, active=s.clock_out, color=theme.ACCENT,
               sub="24 ppq" if s.clock_out else "off")
        learn = row(cells[1], 2, gap=5)
        button(surface, self.hits, "learna", learn[0], "LEARN A", 12,
               sub="wiggle a CC")
        button(surface, self.hits, "learnb", learn[1], "LEARN B", 12,
               sub="wiggle a CC")
        lcd(surface, cells[2], f"{s.bpm:.0f}", size=18, label="BPM")
        lcd(surface, cells[3], f"{s.voices}", size=18, label="NOTES SOUNDING")

    def _file(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "PROJECT + PANEL")
        cells = column(body, 4, gap=6)
        lcd(surface, cells[0], s.project_name[:14], size=15, label="PROJECT")
        files = row(cells[1], 2, gap=5)
        button(surface, self.hits, "save", files[0], "SAVE", 14,
               color=theme.ACCENT)
        button(surface, self.hits, "new", files[1], "NEW", 14)
        button(surface, self.hits, "theme", cells[2],
               theme.active(), 13, sub="theme")
        lcd(surface, cells[3], f"{APP_NAME} {__version__}", size=12,
            label="VERSION")
