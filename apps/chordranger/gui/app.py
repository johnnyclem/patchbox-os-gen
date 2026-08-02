"""The pygame shell: transport rail, tab rail, and one screen at a time.

The App is a *client* of the engine. It reads a snapshot each frame, hands it
to the visible screen, collects the commands that screen produced, and posts
them. It never touches engine state and never blocks the tick thread — closing
this window stops the picture, not the music.

File work (save, load, browse) happens here rather than in the engine for the
same reason: opening a file blocks, and the one thread that must never block
is the one keeping time.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pygame

from core import commands as cmd
from core.chordset import factory_chordsets
from core.commands import EngineSnapshot
from core.project import EXTENSION, Project, list_projects
from core.style import SECTION_LABELS
from core.version import APP_NAME, __version__
from data.styles import factory_styles
from gui import theme
from gui.screens.band import BandScreen
from gui.screens.chord import ChordScreen
from gui.screens.perform import PerformScreen
from gui.screens.settings import SettingsScreen
from gui.screens.song import SongScreen
from gui.widgets import HitMap, button, column, lcd, panel, row, text

log = logging.getLogger("chordranger.gui")

SCREENS = (PerformScreen, ChordScreen, BandScreen, SongScreen,
           SettingsScreen)
MESSAGE_MS = 2500


class App:
    """The window, the chrome, and the screen stack."""

    def __init__(self, engine, size=(theme.WIDTH, theme.HEIGHT),
                 fullscreen: bool = False, config=None,
                 project_path: Path | None = None) -> None:
        self.engine = engine
        self.config = config
        self.project_path = project_path
        self.running = False
        self._message = ""
        self._message_until = 0
        self._edit_target = 0
        self._chordsets = factory_chordsets()
        self._styles = factory_styles()
        self._ports: tuple[str, ...] = ()

        pygame.display.init()
        pygame.font.init()
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.surface = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(f"{APP_NAME} {__version__}")
        pygame.mouse.set_visible(not fullscreen)
        self.clock = pygame.time.Clock()

        self.layout = theme.Layout.for_size(size, len(SCREENS))
        self.chrome = HitMap()
        self.screens = [screen(self, self.layout.content)
                        for screen in SCREENS]
        self.tab = 0
        self.refresh_ports()

    # --- Host protocol -------------------------------------------------------
    def now_ms(self) -> int:
        return pygame.time.get_ticks()

    def set_tab(self, name: str) -> None:
        for index, screen in enumerate(self.screens):
            if screen.title == name:
                self._switch(index)
                return

    def message(self, text_value: str) -> None:
        self._message = text_value
        self._message_until = self.now_ms() + MESSAGE_MS

    def edit_target(self) -> int:
        return self._edit_target

    def set_edit_target(self, index: int) -> None:
        self._edit_target = index

    # --- files ---------------------------------------------------------------
    def _projects_dir(self) -> Path:
        if self.config is not None:
            return self.config.paths.projects_dir
        return Path("data/projects")

    def projects(self) -> tuple[str, ...]:
        return tuple(p.stem for p in list_projects(self._projects_dir()))

    def chordsets(self) -> tuple[str, ...]:
        return tuple(c.name for c in self._chordsets)

    def styles(self) -> tuple[str, ...]:
        return tuple(s.name for s in self._styles)

    def save_project(self) -> None:
        project = self.engine.capture()
        path = self.project_path or (
            self._projects_dir() / f"{project.name.lower()}{EXTENSION}")
        try:
            project.save(path)
        except OSError as exc:
            # A read-only data partition is a real field failure; say so on
            # the panel rather than only in a log nobody is reading on stage.
            log.warning("save failed: %s", exc)
            self.message("SAVE FAILED")
            return
        self.project_path = path
        self.message(f"SAVED {path.stem.upper()}")

    def load_project(self, index: int) -> None:
        paths = list_projects(self._projects_dir())
        if index >= len(paths):
            return
        try:
            project = Project.load(paths[index])
        except (OSError, ValueError) as exc:
            log.warning("load failed: %s", exc)
            self.message("LOAD FAILED")
            return
        self.project_path = paths[index]
        self.engine.submit(cmd.Stop())
        self.engine.submit(cmd.SetChordset(project.chordset))
        self.engine.submit(cmd.SetStyle(project.style))
        self.engine.submit(cmd.SetSong(project.song))
        self.engine.submit(cmd.SetTempo(project.bpm))
        self.engine.submit(cmd.SetVoicing(project.voicing))
        self.engine.submit(cmd.SetBass(project.bass))
        self.engine.submit(cmd.SetSongMode(project.song_mode))
        self.message(f"LOADED {project.name}")

    def new_project(self) -> None:
        from core.project import default_project
        project = default_project()
        self.project_path = None
        self.engine.submit(cmd.Stop())
        self.engine.submit(cmd.SetChordset(project.chordset))
        self.engine.submit(cmd.SetStyle(project.style))
        self.engine.submit(cmd.SetSong(project.song))
        self.message("NEW PROJECT")

    def load_chordset(self, index: int) -> None:
        if index < len(self._chordsets):
            self.engine.submit(cmd.SetChordset(self._chordsets[index]))
            self.message(self._chordsets[index].name)

    def save_chordset(self) -> None:
        chordset = self.engine.chordset
        directory = (self.config.paths.chordsets_dir if self.config is not None
                     else Path("data/chordsets"))
        try:
            chordset.save(directory / f"{chordset.name.lower()}.json")
        except OSError as exc:
            log.warning("chordset save failed: %s", exc)
            self.message("SAVE FAILED")
            return
        self.message(f"SET SAVED: {chordset.name}")

    def load_style(self, index: int) -> None:
        if index < len(self._styles):
            self.engine.submit(cmd.SetStyle(self._styles[index]))
            self.message(self._styles[index].name)

    def refresh_ports(self) -> None:
        try:
            self._ports = tuple(dict.fromkeys(
                p.name for p in self.engine.midi.scan() if not p.is_input))
        except Exception as exc:        # pragma: no cover - backend specific
            log.debug("port scan failed: %s", exc)
            self._ports = ()

    def midi_ports(self) -> tuple[str, ...]:
        return self._ports

    def bind_output(self, name: str) -> None:
        self.engine.submit(cmd.BindOutput("out", name))
        self.message(f"OUT ▸ {name[:14]}")

    def cycle_theme(self) -> None:
        names = theme.COLORWAY_NAMES
        here = names.index(theme.active())
        theme.apply(names[(here + 1) % len(names)])
        self.message(theme.COLORWAYS[theme.active()].label)

    def set_theme(self, name: str) -> None:
        theme.apply(name)

    # --- loop ----------------------------------------------------------------
    def run(self) -> int:
        self.running = True
        fps = self.config.display.fps if self.config is not None else 60
        while self.running:
            self._events()
            snapshot = self.engine.snapshot()
            screen = self.screens[self.tab]
            for command in screen.poll():
                self.engine.submit(command)
            screen.update(snapshot)
            self._draw(snapshot)
            pygame.display.flip()
            self.clock.tick(fps)
        return 0

    def _events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.KEYDOWN and self._key(event):
                continue
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                if self._chrome_event(event):
                    continue
            for command in self.screens[self.tab].handle(event):
                self.engine.submit(command)

    def _key(self, event) -> bool:
        """Keyboard shortcuts for the bench. The appliance has no keyboard,
        but a developer without these is testing with a mouse, one tap at a
        time, which is not testing."""
        if event.key == pygame.K_ESCAPE:
            self.running = False
        elif event.key == pygame.K_SPACE:
            self.engine.submit(cmd.TogglePlay())
        elif event.key == pygame.K_TAB:
            self._switch((self.tab + 1) % len(self.screens))
        elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            delta = 1 if event.key == pygame.K_RIGHTBRACKET else -1
            self.engine.submit(cmd.NudgeTempo(delta))
        elif event.key == pygame.K_p:
            self.engine.submit(cmd.Panic())
        elif pygame.K_1 <= event.key <= pygame.K_9:
            index = event.key - pygame.K_1
            self.engine.submit(cmd.PadDown(index))
            self.engine.submit(cmd.PadUp(index))
        else:
            return False
        return True

    def _chrome_event(self, event) -> bool:
        if event.type != pygame.MOUSEBUTTONUP or event.button != 1:
            return self.chrome.hit(event.pos) is not None
        key = self.chrome.hit(event.pos)
        if key is None:
            return False
        if key.startswith("tab"):
            self._switch(int(key[3:]))
        elif key == "play":
            self.engine.submit(cmd.TogglePlay())
        elif key == "stop":
            self.engine.submit(cmd.Stop())
        elif key == "rec":
            snapshot = self.engine.snapshot()
            self.engine.submit(cmd.SetRecord(not snapshot.recording))
        elif key == "bpm-":
            self.engine.submit(cmd.NudgeTempo(-1))
        elif key == "bpm+":
            self.engine.submit(cmd.NudgeTempo(1))
        elif key == "panic":
            self.engine.submit(cmd.Panic())
        return True

    def _switch(self, index: int) -> None:
        if index == self.tab:
            return
        # Cancel anything held on the outgoing screen, or a pad stays down
        # forever behind a screen nobody can see.
        for command in self.screens[self.tab].cancel_press():
            self.engine.submit(command)
        self.tab = index

    # --- drawing -------------------------------------------------------------
    def _draw(self, snapshot: EngineSnapshot) -> None:
        self.surface.fill(theme.BG)
        self.chrome.clear()
        screen = self.screens[self.tab]
        screen.draw(self.surface)
        self._draw_transport(snapshot)
        self._draw_tabs()
        self._draw_message()

    def _draw_transport(self, snapshot: EngineSnapshot) -> None:
        rect = self.layout.transport
        panel(self.surface, rect, theme.BG)
        cells = column(rect.inflate(-8, -8), 6, gap=5)
        lcd(self.surface, cells[0], f"{snapshot.bpm:.0f}", size=30,
            label="BPM")
        bpm = row(cells[1], 2, gap=4)
        button(self.surface, self.chrome, "bpm-", bpm[0], "−", 20)
        button(self.surface, self.chrome, "bpm+", bpm[1], "+", 20)
        position = f"{snapshot.bar + 1:03d}.{snapshot.beat + 1}"
        lcd(self.surface, cells[2], position, size=22, label="POSITION")
        transport = row(cells[3], 2, gap=4)
        button(self.surface, self.chrome, "play", transport[0],
               "■" if snapshot.playing else "▶", 22,
               active=snapshot.playing, color=theme.ACCENT, display=False)
        button(self.surface, self.chrome, "rec", transport[1], "●", 22,
               active=snapshot.recording, color=theme.ACCENT2, display=False)
        section = SECTION_LABELS.get(snapshot.section, snapshot.section)
        queued = snapshot.next_section
        panel(self.surface, cells[4],
              theme.tint(theme.ACCENT2, 0.3) if queued
              and queued != snapshot.section else theme.BG_RAISED)
        text(self.surface, section, cells[4], 14, theme.TEXT, bold=True,
             display=True)
        button(self.surface, self.chrome, "panic", cells[5], "PANIC", 12,
               color=theme.DANGER)

    def _draw_tabs(self) -> None:
        for index, rect in enumerate(self.layout.tabs):
            screen = self.screens[index]
            active = index == self.tab
            face = theme.SELECT if active else theme.BG_RAISED
            panel(self.surface, rect, face)
            text(self.surface, screen.title, rect, 14, theme.ink_for(face),
                 bold=True, display=True)
            self.chrome.add(f"tab{index}", rect)

    def _draw_message(self) -> None:
        if not self._message or self.now_ms() > self._message_until:
            return
        content = self.layout.content
        rect = pygame.Rect(content.x + 8, content.bottom - 34,
                           min(420, content.width - 16), 26)
        panel(self.surface, rect, theme.ACCENT2, shadow=True)
        text(self.surface, self._message, rect, 14,
             theme.ink_for(theme.ACCENT2), bold=True, display=True)
