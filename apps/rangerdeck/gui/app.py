"""The launch grid — one tile per Ranger app, and the handover dance.

The deck is the only Ranger GUI that is *not* a client of a musical engine.
Its model is the fleet: tap a tile and the deck spawns (or re-greets) that
app, closes its own SDL display, and tells the guest to take the panel.
When the guest's ✕ comes back as ``EVENT HIDDEN`` the deck re-opens the
display and the tile now says RUNNING — the guest's clock, arps and tape
never stopped, only its picture did.

While a guest holds the panel this process draws nothing and blocks in
``fleet.wait_while_shown`` — deliberately. There is exactly one display and
somebody else has it; a deck that kept animating into a dead surface would
only be burning the CPU the guest's audio thread wants.
"""
from __future__ import annotations

import logging
import time

import pygame

from rangerkit.gui import theme, touch
from rangerkit.gui.widgets import HitMap, panel, rule, text

from core.engine import BACKGROUND, OFF, SHOWN, STARTING
from core.version import APP_NAME, __version__

log = logging.getLogger("rangerdeck.gui")

HEADER_H = 52
MARGIN = 10
GAP = 8
STOP_SIZE = 34
MESSAGE_MS = 2500
ATTACH_TIMEOUT = 30.0   # rig build under a cold venv can take a while


class App:
    """The window, the grid, and the blocking visits to guest apps."""

    def __init__(self, fleet, size=(theme.WIDTH, theme.HEIGHT),
                 fullscreen: bool = False, config=None) -> None:
        self.fleet = fleet
        self.size = size
        self.fullscreen = fullscreen
        self.config = config
        self.running = False
        self._message = ""
        self._message_until = 0
        self.chrome = HitMap()
        # Capacitive HID panels emit FINGER* only; the unit pins SDL's mouse
        # synthesis off. Own the translation so a tap can launch a tile.
        mode = touch.configure()
        self.touch = touch.TouchTranslator(size, mode)
        log.info("touch: %s (%s)", mode, self.touch.status())
        self._open_display()
        self.clock = pygame.time.Clock()

    # --- display -------------------------------------------------------------
    def _open_display(self, attempts: int = 10) -> None:
        """Open (or re-open) the panel. Retries because the guest that just
        hid releases DRM master a beat after it says HIDDEN."""
        pygame.font.init()
        flags = pygame.FULLSCREEN if self.fullscreen else 0
        last: Exception | None = None
        for _ in range(attempts):
            try:
                pygame.display.init()
                self.surface = pygame.display.set_mode(self.size, flags)
                break
            except pygame.error as exc:
                last = exc
                pygame.display.quit()
                time.sleep(0.4)
        else:
            raise RuntimeError(f"panel would not open: {last}")
        pygame.display.set_caption(f"{APP_NAME} {__version__}")
        pygame.mouse.set_visible(not self.fullscreen)
        self.touch.resize(self.size)

    # --- host protocol -------------------------------------------------------
    def now_ms(self) -> int:
        return pygame.time.get_ticks()

    def message(self, text_value: str) -> None:
        self._message = text_value
        self._message_until = self.now_ms() + MESSAGE_MS

    # --- loop ----------------------------------------------------------------
    def run(self) -> int:
        self.running = True
        fps = self.config.display.fps if self.config is not None else 60
        while self.running:
            self._events()
            self.fleet.poll()
            self._draw()
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
            if event.type == pygame.KEYDOWN \
                    and event.key == pygame.K_ESCAPE:
                self.running = False
                return
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                key = self.chrome.hit(event.pos)
                if key is None:
                    continue
                kind, _, name = key.partition(":")
                if kind == "app":
                    self._visit(name)
                elif kind == "stop":
                    self._stop(name)

    # --- visiting a guest ----------------------------------------------------
    def _visit(self, name: str) -> None:
        guest_title = self.fleet.guests[name].spec.title
        if self.fleet.state(name) == OFF:
            if not self.fleet.launch(name):
                self.message(f"{guest_title.upper()}: SPAWN FAILED")
                return
        if not self._await_attach(name, guest_title):
            return
        # The handover proper. Order is the whole protocol: our display
        # closes before SHOW goes out, and it reopens only after the guest
        # said HIDDEN/QUIT (or provably never took the panel).
        pygame.display.quit()
        self.fleet.show(name)
        outcome = self.fleet.wait_while_shown(name)
        self._open_display()
        if outcome == "failed":
            self.message(f"{guest_title.upper()}: PANEL HANDOVER FAILED")
        elif outcome == "quit":
            self.message(f"{guest_title.upper()} CLOSED")

    def _await_attach(self, name: str, guest_title: str) -> bool:
        """Animate STARTING until the guest's deck socket answers."""
        deadline = time.monotonic() + ATTACH_TIMEOUT
        while not self.fleet.try_attach(name, timeout=0.2):
            self.fleet.poll()
            if self.fleet.state(name) == OFF:
                self.message(f"{guest_title.upper()} DIED ON START — "
                             "SEE JOURNAL")
                return False
            if time.monotonic() > deadline:
                self.fleet.stop(name)
                self.message(f"{guest_title.upper()}: NO ANSWER — STOPPED")
                return False
            for raw in pygame.event.get():
                event = self.touch.translate(raw)
                if event is not None and event.type == pygame.QUIT:
                    self.running = False
                    return False
            self._draw()
            pygame.display.flip()
            self.clock.tick(30)
        return True

    def _stop(self, name: str) -> None:
        guest_title = self.fleet.guests[name].spec.title
        self.fleet.stop(name)
        self.message(f"{guest_title.upper()} STOPPING")

    # --- drawing -------------------------------------------------------------
    def _draw(self) -> None:
        self.surface.fill(theme.BG)
        self.chrome.clear()
        self._draw_header()
        self._draw_grid()
        self._draw_message()

    def _draw_header(self) -> None:
        rect = pygame.Rect(0, 0, self.size[0], HEADER_H)
        panel(self.surface, rect, theme.BG)
        title = pygame.Rect(rect.x + 14, rect.y, 360, rect.height)
        text(self.surface, "RANGER SUITE", title, 24, theme.TEXT, bold=True,
             display=True, align="left")
        running = self.fleet.running_count()
        status = f"{running} RUNNING" if running else "TAP A TILE TO LAUNCH"
        right = pygame.Rect(rect.right - 374, rect.y, 360, rect.height)
        text(self.surface, status, right, 14,
             theme.ACCENT if running else theme.TEXT_DIM, bold=True,
             display=True, align="right")
        rule(self.surface, pygame.Rect(rect.x, rect.bottom - theme.BORDER_W,
                                       rect.width, theme.BORDER_W))

    def _grid_cells(self, count: int) -> list[pygame.Rect]:
        area = pygame.Rect(MARGIN, HEADER_H + MARGIN,
                           self.size[0] - 2 * MARGIN,
                           self.size[1] - HEADER_H - 2 * MARGIN)
        columns = 4 if theme.is_wide(self.size) else 2
        rows = max(1, -(-count // columns))
        cell_w = (area.width - (columns - 1) * GAP) // columns
        cell_h = (area.height - (rows - 1) * GAP) // rows
        cells = []
        for index in range(count):
            row_i, col_i = divmod(index, columns)
            cells.append(pygame.Rect(area.x + col_i * (cell_w + GAP),
                                     area.y + row_i * (cell_h + GAP),
                                     cell_w, cell_h))
        return cells

    def _draw_grid(self) -> None:
        names = self.fleet.names()
        for index, (name, cell) in enumerate(zip(names,
                                                 self._grid_cells(
                                                     len(names)))):
            self._draw_tile(index, name, cell)

    def _draw_tile(self, index: int, name: str, cell: pygame.Rect) -> None:
        guest = self.fleet.guests[name]
        state = guest.state
        hue = theme.part_color(index)
        face = theme.tint(hue, 0.30 if state != OFF else 0.14)
        panel(self.surface, cell, face, shadow=state != OFF)
        self.chrome.add(f"app:{name}", cell)
        ink = theme.ink_for(face)
        title = pygame.Rect(cell.x + 12, cell.y + 8,
                            cell.width - STOP_SIZE - 24, 30)
        text(self.surface, guest.spec.title.upper(), title, 20, ink,
             bold=True, display=True, align="left")
        tagline = pygame.Rect(cell.x + 12, cell.y + 40, cell.width - 24, 18)
        text(self.surface, guest.spec.tagline, tagline, 12,
             theme.blend(ink, face, 0.35), align="left")
        status_rect = pygame.Rect(cell.x + 12, cell.bottom - 26,
                                  cell.width - 24, 18)
        status, color = {
            OFF: ("", ink),
            STARTING: (guest.note or "STARTING", theme.WARN),
            BACKGROUND: (guest.note or "RUNNING", theme.ACCENT),
            SHOWN: ("ON PANEL", theme.ACCENT),
        }[state]
        if status:
            text(self.surface, status, status_rect, 12, color, bold=True,
                 display=True, align="left")
        if state != OFF:
            stop = pygame.Rect(cell.right - STOP_SIZE - 8, cell.y + 8,
                               STOP_SIZE, STOP_SIZE)
            panel(self.surface, stop, theme.tint(theme.DANGER, 0.14))
            # Display family: DejaVu carries U+25A0; the mono falls back to
            # a notdef box.
            text(self.surface, "■", stop, 14,
                 theme.ink_for(theme.tint(theme.DANGER, 0.14)),
                 display=True)
            self.chrome.add(f"stop:{name}", stop)

    def _draw_message(self) -> None:
        if not self._message or self.now_ms() > self._message_until:
            return
        rect = pygame.Rect(MARGIN + 8, self.size[1] - 36,
                           min(480, self.size[0] - 2 * MARGIN - 16), 26)
        panel(self.surface, rect, theme.ACCENT2, shadow=True)
        text(self.surface, self._message, rect, 14,
             theme.ink_for(theme.ACCENT2), bold=True, display=True)
