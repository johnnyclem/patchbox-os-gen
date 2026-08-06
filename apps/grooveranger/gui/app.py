"""The pygame shell: transport rail, tab rail, and one screen at a time.

The App is a *client* of the engine. It reads a snapshot each frame, hands
it to the visible screen, collects the commands that screen produced, and
posts them. It never touches engine state and never blocks the tick thread.

Two GrooveRanger-specific duties live here because they are file and
device work, not music: kit browsing (kit.json parsing happens on this
thread, the result goes to the engine as a command and to the sampler as a
parameter swap), and keeping the sampler's kit and tempo in step with the
snapshot — the ``kit_rev`` field says when the engine's kit changed under
us.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pygame

from rangerkit import enginebase as base
from rangerkit.gui import theme
from rangerkit.gui.widgets import HitMap, button, close_badge, column, lcd, \
    panel, row, text

from core import commands as cmd
from core.commands import GrSnapshot
from core.kit import list_kits, load_kit
from core.project import EXTENSION
from core.version import APP_NAME, __version__
from gui.screens.kit import KitScreen
from gui.screens.perform import PerformScreen
from gui.screens.seq import SeqScreen
from gui.screens.settings import SettingsScreen
from gui.screens.song import SongScreen

log = logging.getLogger("grooveranger.gui")

SCREENS = (PerformScreen, SeqScreen, KitScreen, SongScreen,
           SettingsScreen)
MESSAGE_MS = 2500


def _transport_row(rect, pairs=(1,), count: int = 5, gap: int = 5):
    """Slice a horizontal transport band into *count* cells, giving the
    paired-button cells their touch floor first (see ChordRanger's shell
    for the full derivation — same arithmetic, one fewer pair)."""
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
                 sampler=None, deck: bool = False) -> None:
        self.engine = engine
        self.config = config
        self.project_path = project_path
        self.pots = pots
        self.sampler = sampler
        # Under the RangerDeck launcher the chrome grows a ✕ that closes the
        # picture and nothing else; run() reports which exit the user took
        # through exit_reason ("hide" back to the deck, "quit" for real).
        self.deck = deck
        self.exit_reason = "quit"
        self.running = False
        self._message = ""
        self._message_until = 0
        self._ports: tuple[str, ...] = ()
        self._kit_rev = -1

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
        self.engine.submit(cmd.RecallProjectState(project.params))
        self.message("NEW PROJECT")

    def wire_save(self, button_server) -> None:
        button_server.actions["save_project"] = self.save_project

    # --- kits ----------------------------------------------------------------
    def load_kit_step(self, direction: int) -> None:
        """Walk the kit directories; parse on this thread, then tell the
        engine (a command) and the sampler (a parameter swap)."""
        kits = list_kits(self.config)
        if not kits:
            self.message("NO KITS FOUND")
            return
        names = [entry.name for entry in kits]
        current = self.engine.kit.name
        here = names.index(current) if current in names else -1
        target = kits[(here + direction) % len(kits)]
        try:
            kit = load_kit(target)
        except (OSError, ValueError) as exc:
            log.warning("kit %s unreadable: %s", target.name, exc)
            self.message(f"BAD KIT {target.name.upper()[:10]}")
            return
        self.engine.submit(cmd.LoadKitState(params=kit.to_config()))

    def _sync_sampler(self, snapshot: GrSnapshot) -> None:
        if self.sampler is None:
            return
        self.sampler.set_tempo(snapshot.bpm)
        if snapshot.kit_rev != self._kit_rev:
            self._kit_rev = snapshot.kit_rev
            # engine.kit is an immutable value; reading the reference from
            # this thread is safe, and set_kit does its file work here.
            self.sampler.set_kit(self.engine.kit)

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
        if endpoint.endswith("_in"):
            self.engine.submit(base.BindInput(endpoint, port))
        else:
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
            self._sync_sampler(snapshot)
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
            self.engine.submit(base.TogglePlay())
        elif event.key == pygame.K_TAB:
            self._switch((self.tab + 1) % len(self.screens))
        elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            delta = 1 if event.key == pygame.K_RIGHTBRACKET else -1
            self.engine.submit(base.NudgeTempo(delta))
        elif event.key == pygame.K_p:
            self.engine.submit(base.Panic())
        elif event.key == pygame.K_f:
            self.engine.submit(cmd.QueueFill())
        elif event.key == pygame.K_r:
            snapshot = self.engine.snapshot()
            self.engine.submit(base.SetRecord(on=not snapshot.recording))
        elif pygame.K_1 <= event.key <= pygame.K_8:
            self.engine.submit(cmd.SelectPattern(
                index=event.key - pygame.K_1))
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
        elif key == "fill":
            self.engine.submit(cmd.QueueFill())
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
        for command in self.screens[self.tab].cancel_press():
            self.engine.submit(command)
        self.tab = index

    # --- drawing -------------------------------------------------------------
    def _draw(self, snapshot: GrSnapshot) -> None:
        self.surface.fill(theme.BG)
        self.chrome.clear()
        screen = self.screens[self.tab]
        screen.draw(self.surface)
        self._draw_transport(snapshot)
        self._draw_tabs()
        if self.layout.close is not None:
            close_badge(self.surface, self.chrome, self.layout.close)
        self._draw_message()

    def _draw_transport(self, snapshot: GrSnapshot) -> None:
        """Five transport controls along whichever axis the chrome runs:
        BPM readout, nudge pair, RUN, FILL, PANIC."""
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
               sub=f"P{snapshot.pattern_index + 1}"
               + (f"▸P{snapshot.queued + 1}" if snapshot.queued >= 0
                  else ""))
        button(self.surface, self.chrome, "fill", cells[3], "FILL", 14,
               active=snapshot.fill or snapshot.fill_queued,
               color=theme.ACCENT2,
               sub="queued" if snapshot.fill_queued else "")
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
