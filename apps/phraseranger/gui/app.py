"""The pygame shell: transport rail, tab rail, and one screen at a time.

The App is a *client* of the engine. It reads a snapshot each frame, hands it
to the visible screen, collects the commands that screen produced, and posts
them. It never touches engine state and never blocks the tick thread —
closing this window stops the picture, not the routing.

File work (save, load) happens here rather than in the engine for the same
reason: opening a file blocks, and the one thread that must never block is
the one keeping time.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pygame

from rangerkit import enginebase as base
from rangerkit.gui import theme, touch
from rangerkit.gui.widgets import HitMap, button, close_badge, column, lcd, \
    panel, row, text

from core import commands as cmd
from core.commands import PrSnapshot
from core.project import EXTENSION
from core.version import APP_NAME, __version__
from gui.screens.library import LibraryScreen
from gui.screens.perform import PerformScreen
from gui.screens.routing import RoutingScreen
from gui.screens.settings import SettingsScreen
from gui.screens.slice import SliceScreen

log = logging.getLogger("phraseranger.gui")

SCREENS = (PerformScreen, SliceScreen, RoutingScreen,
           LibraryScreen, SettingsScreen)
MESSAGE_MS = 2500


def _transport_row(rect, pairs=(1,), count: int = 5, gap: int = 5):
    """Slice a horizontal transport band into *count* cells, giving the
    paired-button cells their touch floor first (see ChordRanger's shell for
    the full derivation — same arithmetic, one fewer pair)."""
    inner_gap = 4
    pair_floor = 2 * (theme.TOUCH_MIN + inner_gap)
    spare = rect.width - len(pairs) * (pair_floor + gap)
    others = count - len(pairs)
    other_w = max(theme.TOUCH_MIN, spare // max(1, others)) if others else 0
    cells, x = [], rect.x
    for index in range(count):
        span = pair_floor if index in pairs else other_w
        if index == count - 1:
            span = max(span, rect.right - x)    # absorb the remainder
        cells.append(pygame.Rect(x, rect.y, max(1, span), rect.height))
        x += span + gap
    return cells


class App:
    """The window, the chrome, and the screen stack."""

    def __init__(self, engine, size=(theme.WIDTH, theme.HEIGHT),
                 fullscreen: bool = False, config=None,
                 project_path: Path | None = None, pots=None,
                 deck: bool = False) -> None:
        self.engine = engine
        self.config = config
        self.project_path = project_path
        self.pots = pots
        # Under the RangerDeck launcher the chrome grows a ✕ that closes the
        # picture and nothing else; run() reports which exit the user took
        # through exit_reason ("hide" back to the deck, "quit" for real).
        self.deck = deck
        self.exit_reason = "quit"
        self.running = False
        self._message = ""
        self._message_until = 0
        self._ports: tuple[str, ...] = ()

        # Capacitive HID panels emit FINGER* only; the unit pins SDL's mouse
        # synthesis off. Own the translation so every tap reaches a hit map.
        mode = touch.configure()
        self.touch = touch.TouchTranslator(size, mode)
        log.info("touch: %s (%s)", mode, self.touch.status())

        pygame.display.init()
        pygame.font.init()
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.surface = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(f"{APP_NAME} {__version__}")
        pygame.mouse.set_visible(not fullscreen)
        self.clock = pygame.time.Clock()

        self.layout = theme.Layout.for_size(size, len(SCREENS),
                                            close_button=deck)
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

    # --- files ---------------------------------------------------------------
    def _projects_dir(self) -> Path:
        if self.config is not None:
            return Path(self.config.paths.projects_dir)
        return Path("data/projects")

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

    def new_project(self) -> None:
        from core.project import default_project
        project = default_project()
        self.project_path = None
        self.engine.submit(base.Panic())
        self.engine.project = project
        # Applying a whole state is engine-thread work; go through the queue
        # the way every other state change does.
        self.engine.submit(cmd.RecallProjectState(project.params))
        self.message("NEW PROJECT")

    def wire_save(self, button_server) -> None:
        """With a window up, the App is the authority on which file is
        current; the button's save action goes through it."""
        button_server.actions["save_project"] = self.save_project

    # --- MIDI ----------------------------------------------------------------
    def refresh_ports(self) -> None:
        try:
            self._ports = tuple(dict.fromkeys(
                p.name for p in self.engine.midi.scan()))
        except Exception as exc:        # pragma: no cover - backend specific
            log.debug("port scan failed: %s", exc)
            self._ports = ()

    def midi_ports(self) -> tuple[str, ...]:
        return self._ports

    def bind_endpoint(self, endpoint: str, port: str) -> None:
        self.engine.submit(base.BindOutput(endpoint, port))
        self.message(f"{endpoint.replace('_', ' ').upper()} ▸ {port[:14]}")

    # --- pots / theme ---------------------------------------------------------
    def learn_pot(self, index: int) -> None:
        if self.pots is None:
            self.message("NO POTS SOURCE")
            return
        self.pots.learn(index)
        self.message(f"POT {'AB'[index]}: MOVE A CC…")
        self.pots.on_learned = lambda i, ccnum: self.message(
            f"POT {'AB'[i]} = CC {ccnum}")

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
        for raw in pygame.event.get():
            event = self.touch.translate(raw)
            if event is None:
                continue
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
            self.engine.submit(base.TogglePlay())
        elif event.key == pygame.K_TAB:
            self._switch((self.tab + 1) % len(self.screens))
        elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            delta = 1 if event.key == pygame.K_RIGHTBRACKET else -1
            self.engine.submit(base.NudgeTempo(delta))
        elif event.key == pygame.K_p:
            self.engine.submit(base.Panic())
        elif event.key == pygame.K_u:
            self.engine.submit(cmd.UndoTrack())
        elif event.key == pygame.K_q:
            self.engine.submit(cmd.SetQuantize(
                on=not self.engine.recorder.quantize))
        elif pygame.K_1 <= event.key <= pygame.K_8:
            self.engine.submit(cmd.ArmTrack(index=event.key - pygame.K_1))
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
        elif key == "deck-close":
            self.exit_reason = "hide"
            self.running = False
        elif key == "play":
            self.engine.submit(base.TogglePlay())
        elif key == "take":
            self.engine.submit(cmd.ArmTrack(index=-1))
        elif key == "undo":
            self.engine.submit(cmd.UndoTrack())
        elif key == "bpm-":
            self.engine.submit(base.NudgeTempo(-1))
        elif key == "bpm+":
            self.engine.submit(base.NudgeTempo(1))
        elif key == "panic":
            self.engine.submit(base.Panic())
        return True

    def _switch(self, index: int) -> None:
        if index == self.tab:
            return
        # Cancel anything held on the outgoing screen, or a control stays
        # down forever behind a screen nobody can see.
        for command in self.screens[self.tab].cancel_press():
            self.engine.submit(command)
        self.tab = index

    # --- drawing -------------------------------------------------------------
    def _draw(self, snapshot: PrSnapshot) -> None:
        self.surface.fill(theme.BG)
        self.chrome.clear()
        screen = self.screens[self.tab]
        screen.draw(self.surface)
        self._draw_transport(snapshot)
        self._draw_tabs()
        if self.layout.close is not None:
            close_badge(self.surface, self.chrome, self.layout.close)
        self._draw_message()

    def _draw_transport(self, snapshot: PrSnapshot) -> None:
        """Five transport controls along whichever axis the chrome runs:
        BPM readout, nudge pair, RUN, BYPASS, PANIC."""
        rect = self.layout.transport
        panel(self.surface, rect, theme.BG)
        inner = rect.inflate(-8, -8)
        if self.layout.wide:
            cells = column(inner, 5, gap=5)
        else:
            cells = _transport_row(inner, pairs=(1,), count=5)
        lcd(self.surface, cells[0], f"{snapshot.bpm:.0f}", size=30,
            label="BPM")
        bpm = row(cells[1], 2, gap=4)
        button(self.surface, self.chrome, "bpm-", bpm[0], "−", 20)
        button(self.surface, self.chrome, "bpm+", bpm[1], "+", 20)
        button(self.surface, self.chrome, "play", cells[2],
               "RUN" if snapshot.playing else "HELD", 15,
               active=snapshot.playing, color=theme.ACCENT,
               sub="the loops")
        armed = snapshot.armed
        button(self.surface, self.chrome, "take", cells[3],
               f"T{armed + 1}●" if armed >= 0 else "—", 15,
               active=armed >= 0, color=theme.ACCENT2,
               sub="recording" if armed >= 0 else "no take")
        button(self.surface, self.chrome, "panic", cells[4], "PANIC", 12,
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
