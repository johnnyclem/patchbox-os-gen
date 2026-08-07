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

The last grid cell is not an app: it is POWER. Tap it for Restart /
Shut Down / Cancel — passwordless ``systemctl`` via the deck's sudoers.
"""
from __future__ import annotations

import logging
import subprocess
import time
from typing import Callable

import pygame

from rangerkit.gui import theme, touch
from rangerkit.gui.widgets import (HitMap, button, chip, focus_ring, lcd, pad,
                                   panel, rule, text, toast)

from core.engine import BACKGROUND, OFF, SHOWN, STARTING
from core.updates import (STATUS_APPLYING, STATUS_AVAILABLE, STATUS_CHECKING,
                          STATUS_CURRENT, STATUS_ERROR, UpdateState,
                          apply_update, start_check, update_settings)
from core.version import APP_NAME, __version__

log = logging.getLogger("rangerdeck.gui")

# micro-rangers chrome on the 1280×400 bar (scaled from 320×240 handoff).
STATUS_H = theme.STATUS_H
LEGEND_H = theme.LEGEND_H
MARGIN = theme.PAD_GAP * 2
GAP = theme.PAD_GAP
STOP_SIZE = 36                  # ≥ direct-action floor (design 40×36, touch 44)
MESSAGE_MS = 2500
ATTACH_TIMEOUT = 30.0

# Appliance power. Both /usr/bin and /bin paths: bookworm usually has the
# former; some images still resolve systemctl via /bin. Sudoers grants both.
_SYSTEMCTL = ("/usr/bin/systemctl", "/bin/systemctl")
POWER_ACTIONS = ("restart", "shutdown")  # menu order before Cancel


def _systemctl_argv(verb: str) -> list[str]:
    """``sudo -n systemctl <verb>`` — -n so a missing sudoers is a clean fail
    rather than a hung password prompt on a headless kiosk."""
    return ["sudo", "-n", _SYSTEMCTL[0], verb]


def default_power_runner(action: str) -> tuple[bool, str]:
    """Run a power action. Returns (ok, human message). Injected in tests."""
    if action == "restart":
        argv = _systemctl_argv("reboot")
        label = "RESTART"
    elif action == "shutdown":
        argv = _systemctl_argv("poweroff")
        label = "SHUT DOWN"
    else:
        return False, f"unknown power action: {action}"
    try:
        result = subprocess.run(argv, check=False, capture_output=True,
                                text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("power %s failed: %s", action, exc)
        return False, f"{label} FAILED"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip().splitlines()
        detail = err[-1] if err else f"exit {result.returncode}"
        log.warning("power %s: %s", action, detail)
        return False, f"{label} FAILED — CHECK SUDOERS"
    return True, f"{label}…"


class App:
    """The window, the grid, and the blocking visits to guest apps."""

    def __init__(self, fleet, size=(theme.WIDTH, theme.HEIGHT),
                 fullscreen: bool = False, config=None,
                 power_runner: Callable[[str], tuple[bool, str]] | None = None,
                 update_state: UpdateState | None = None,
                 update_apply: Callable[[], tuple[bool, str]] | None = None,
                 start_update_check: bool = True) -> None:
        self.fleet = fleet
        self.size = size
        self.fullscreen = fullscreen
        self.config = config
        self.running = False
        self._message = ""
        self._message_until = 0
        self._power_menu = False
        self._update_menu = False
        self._power_runner = power_runner or default_power_runner
        self._update_apply = update_apply
        self.updates = update_state or UpdateState()
        self._update_settings = update_settings(config)
        self.chrome = HitMap()
        # Capacitive HID panels emit FINGER* only; the unit pins SDL's mouse
        # synthesis off. Own the translation so a tap can launch a tile.
        mode = touch.configure()
        self.touch = touch.TouchTranslator(size, mode)
        log.info("touch: %s (%s)", mode, self.touch.status())
        self._open_display()
        self.clock = pygame.time.Clock()
        if start_update_check:
            start_check(self._update_settings, self.updates)

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
                if self._power_menu:
                    self._power_menu = False
                    continue
                if self._update_menu:
                    self._update_menu = False
                    continue
                self.running = False
                return
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                key = self.chrome.hit(event.pos)
                if key is None:
                    continue
                if key == "update:open":
                    self._update_menu = True
                    self._power_menu = False
                    continue
                if key == "update:later" or key == "update:backdrop":
                    self._update_menu = False
                    continue
                if key == "update:install":
                    self._install_update()
                    continue
                if key == "power:open":
                    self._power_menu = True
                    self._update_menu = False
                    continue
                if key == "power:cancel" or key == "power:backdrop":
                    self._power_menu = False
                    continue
                if key == "power:restart":
                    self._power("restart")
                    continue
                if key == "power:shutdown":
                    self._power("shutdown")
                    continue
                # App tiles are inert while a confirm sheet is up — a fat
                # finger past the sheet edge must not launch something.
                if self._power_menu or self._update_menu:
                    continue
                kind, _, name = key.partition(":")
                if kind == "app":
                    self._visit(name)
                elif kind == "stop":
                    self._stop(name)

    def _power(self, action: str) -> None:
        """Confirm sheet choice: stop every guest, then reboot / poweroff."""
        self._power_menu = False
        # Guests first so note-offs go out before the kernel pulls the plug.
        try:
            self.fleet.shutdown()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("fleet shutdown before power: %s", exc)
        ok, line = self._power_runner(action)
        self.message(line)
        if ok and action in POWER_ACTIONS:
            # Give the message a frame to paint; the process may die next.
            self._draw()
            pygame.display.flip()

    def _install_update(self) -> None:
        """Apply the channel update: stop guests, run the privileged script."""
        self._update_menu = False
        self.message("INSTALLING UPDATE…")
        self._draw()
        pygame.display.flip()
        try:
            self.fleet.shutdown()
        except Exception as exc:  # pragma: no cover
            log.warning("fleet shutdown before update: %s", exc)
        ok, line = apply_update(self.updates, runner=self._update_apply)
        self.message(line)
        # The updater restarts rangerdeck on success — if we are still here,
        # either it failed or we are on a dev box without the service.
        if ok:
            log.info("update applied: %s", line)

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
        # Outer panel face (industrial BG) with a hard frame — the micro-rangers
        # "bezel" so content never bleeds into the void.
        self.surface.fill(theme.BORDER)
        face = pygame.Rect(2, 2, self.size[0] - 4, self.size[1] - 4)
        self.surface.fill(theme.BG, face)
        self.chrome.clear()
        self._draw_status_ribbon()
        self._draw_grid()
        self._draw_legend()
        if self._update_menu:
            self._draw_update_menu()
        if self._power_menu:
            self._draw_power_menu()
        self._draw_message()

    def _content_area(self) -> pygame.Rect:
        return pygame.Rect(MARGIN, STATUS_H + MARGIN,
                           self.size[0] - 2 * MARGIN,
                           self.size[1] - STATUS_H - LEGEND_H - 2 * MARGIN)

    def _draw_status_ribbon(self) -> None:
        """Top band: play lamp · suite title · running count LCD · INT/update."""
        rect = pygame.Rect(0, 0, self.size[0], STATUS_H)
        self.surface.fill(theme.BG_RAISED, rect)
        rule(self.surface, pygame.Rect(0, rect.bottom - theme.BORDER_W,
                                       rect.width, theme.BORDER_W))

        running = self.fleet.running_count()
        # Play lamp — lit when any guest is running (LAUNCH transport voice).
        # Geometry, not unicode: display fonts often box ▶/■ on the Pi.
        lamp = pygame.Rect(8, 6, STATUS_H - 12, STATUS_H - 12)
        face = theme.ACCENT if running else theme.BG_SUNKEN
        panel(self.surface, lamp, face)
        ink = theme.ink_for(face)
        self._glyph_play(lamp, ink) if running else self._glyph_stop(lamp, ink)

        title = pygame.Rect(lamp.right + 10, 0, 200, STATUS_H)
        text(self.surface, "RANGER", title, 16, theme.TEXT, bold=True,
             display=True, align="left")

        # Running count as an LCD well (numbers live in black wells).
        count_rect = pygame.Rect(title.right + 8, 6, 110, STATUS_H - 12)
        lcd(self.surface, count_rect, f"{running:02d}", size=20, label="RUN")

        ustatus, _local, remote, detail = self.updates.snapshot()
        right = pygame.Rect(self.size[0] - 280, 6, 268, STATUS_H - 12)
        if ustatus == STATUS_AVAILABLE:
            label = f"UPDATE {remote.version or remote.short_commit() or ''}".strip()
            chip(self.surface, right, f"{label} · TAP", color=theme.WARN,
                 active=True)
            self.chrome.add("update:open", right)
        else:
            if ustatus == STATUS_CHECKING:
                line, color = "CHECKING…", theme.DISPLAY_DIM
            elif ustatus == STATUS_APPLYING:
                line, color = "INSTALLING…", theme.WARN
            elif ustatus == STATUS_ERROR:
                line, color = "OFFLINE", theme.TEXT_DIM
            else:
                line, color = "INT", theme.DISPLAY_DIM
            text(self.surface, line, right, 13, color, bold=True,
                 display=True, align="right")

    def _draw_legend(self) -> None:
        """Bottom encoder legend strip — always-on copy, never steals focus."""
        rect = pygame.Rect(0, self.size[1] - LEGEND_H, self.size[0], LEGEND_H)
        self.surface.fill(theme.BG_RAISED, rect)
        rule(self.surface, pygame.Rect(0, rect.y, rect.width, theme.BORDER_W))
        half = rect.width // 2
        left = pygame.Rect(8, rect.y, half - 16, rect.height)
        right = pygame.Rect(half + 4, rect.y, half - 60, rect.height)
        text(self.surface, "ENC1 > TAP TILE · LAUNCH", left, 12, theme.TEXT,
             bold=True, display=True, align="left")
        text(self.surface, "ENC2 > STOP · POWER", right, 12, theme.TEXT,
             bold=True, display=True, align="left")
        x1 = pygame.Rect(rect.right - 44, rect.y + 6, 36, rect.height - 12)
        panel(self.surface, x1, theme.BG_SUNKEN)
        text(self.surface, "×1", x1, 11, theme.TEXT, bold=True, display=True)

    def _grid_cells(self, count: int) -> list[pygame.Rect]:
        area = self._content_area()
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
        cells = self._grid_cells(len(names) + 1)
        for index, name in enumerate(names):
            self._draw_tile(index, name, cells[index])
        self._draw_power_tile(cells[len(names)])

    def _pad_state(self, state: str) -> str:
        return {
            OFF: "stopped",
            STARTING: "queued",
            BACKGROUND: "playing",
            SHOWN: "playing",
        }.get(state, "stopped")

    def _draw_tile(self, index: int, name: str, cell: pygame.Rect) -> None:
        guest = self.fleet.guests[name]
        state = guest.state
        hue = theme.part_color(index)
        pad_state = self._pad_state(state)
        pad(self.surface, cell, state=pad_state, hue=hue,
            label=guest.spec.title, sub=guest.spec.tagline, chip=hue)
        if state == SHOWN:
            focus_ring(self.surface, cell)
        # Centre state mark (geometry — fonts box unicode on the appliance).
        if state in (BACKGROUND, SHOWN) and cell.height >= 100:
            mark = pygame.Rect(cell.centerx - 12, cell.centery - 4, 24, 24)
            self._glyph_play(mark, theme.ink_for(
                theme.blend(theme.BG_RAISED, hue, 0.72)))
        elif state == STARTING and cell.height >= 100:
            text(self.surface, "...",
                 pygame.Rect(cell.x, cell.centery - 8, cell.width, 20),
                 16, theme.HOT, bold=True, display=True)
        self.chrome.add(f"app:{name}", cell)
        if state != OFF:
            status = guest.note or ("ON PANEL" if state == SHOWN else "RUNNING")
            status_rect = pygame.Rect(cell.x + 8, cell.bottom - 22,
                                      max(40, cell.width - STOP_SIZE - 20), 16)
            text(self.surface, status, status_rect, 11, theme.DISPLAY,
                 bold=True, display=True, align="left")
            stop = pygame.Rect(cell.right - STOP_SIZE - 6, cell.y + 6,
                               STOP_SIZE, STOP_SIZE)
            button(self.surface, self.chrome, f"stop:{name}", stop, "X", 14,
                   kind="dang")

    def _draw_power_tile(self, cell: pygame.Rect) -> None:
        """DANG home pad — destructive actions live here, never on app tiles."""
        face = theme.blend(theme.BG_RAISED, theme.DANGER, 0.40)
        panel(self.surface, cell, face, shadow=False)
        badge = pygame.Rect(cell.x + 4, cell.y + 4, 14, 10)
        self.surface.fill(theme.DANGER, badge)
        rule(self.surface, badge, width=1)
        ink = theme.ink_for(face)
        text(self.surface, "POWER",
             pygame.Rect(cell.x + 8, cell.y + 20, cell.width - 16, 24),
             16, ink, bold=True, display=True, align="left")
        text(self.surface, "RESTART · SHUT DOWN",
             pygame.Rect(cell.x + 8, cell.y + 48, cell.width - 16, 16),
             11, theme.blend(ink, face, 0.35), display=True, align="left")
        # Power glyph: circle + stem (unicode ⏻ is often a notdef box).
        cx, cy = cell.centerx, cell.bottom - 28
        pygame.draw.circle(self.surface, ink, (cx, cy + 4), 10, 2)
        pygame.draw.line(self.surface, ink, (cx, cy - 8), (cx, cy + 2), 2)
        self.chrome.add("power:open", cell)

    def _glyph_play(self, rect: pygame.Rect, color) -> None:
        cx, cy = rect.center
        pygame.draw.polygon(self.surface, color,
                            [(cx - 5, cy - 7), (cx - 5, cy + 7), (cx + 7, cy)])

    def _glyph_stop(self, rect: pygame.Rect, color) -> None:
        r = pygame.Rect(0, 0, 10, 10)
        r.center = rect.center
        self.surface.fill(color, r)

    def _draw_power_menu(self) -> None:
        """Modal: PRIM / DANG / NEUT buttons over a dim LCD veil."""
        backdrop = pygame.Rect(0, 0, self.size[0], self.size[1])
        veil = pygame.Surface(self.size, pygame.SRCALPHA)
        veil.fill((*theme.BG_LCD, 170))
        self.surface.blit(veil, (0, 0))
        self.chrome.add("power:backdrop", backdrop)

        sheet_w = min(440, self.size[0] - 2 * MARGIN)
        btn_h = max(theme.TOUCH_MIN + 8, 52)
        gap, pad, header_h = GAP, 14, 36
        sheet_h = pad + header_h + 3 * (btn_h + gap) - gap + pad
        sheet = pygame.Rect((self.size[0] - sheet_w) // 2,
                            (self.size[1] - sheet_h) // 2,
                            sheet_w, sheet_h)
        panel(self.surface, sheet, theme.BG, shadow=True, focus=True)
        head = pygame.Rect(sheet.x + pad, sheet.y + pad,
                           sheet.width - 2 * pad, header_h)
        text(self.surface, "POWER", head, 18, theme.TEXT, bold=True,
             display=True, align="left")
        y = head.bottom + 4
        for key, label, kind in (
                ("power:restart", "RESTART", "prim"),
                ("power:shutdown", "SHUT DOWN", "dang"),
                ("power:cancel", "CANCEL", "neut")):
            rect = pygame.Rect(sheet.x + pad, y, sheet.width - 2 * pad, btn_h)
            button(self.surface, self.chrome, key, rect, label, 18, kind=kind)
            y += btn_h + gap

    def _draw_update_menu(self) -> None:
        """Modal: Install (PRIM) / Later (NEUT)."""
        _status, local, remote, detail = self.updates.snapshot()
        backdrop = pygame.Rect(0, 0, self.size[0], self.size[1])
        veil = pygame.Surface(self.size, pygame.SRCALPHA)
        veil.fill((*theme.BG_LCD, 170))
        self.surface.blit(veil, (0, 0))
        self.chrome.add("update:backdrop", backdrop)

        sheet_w = min(520, self.size[0] - 2 * MARGIN)
        btn_h = max(theme.TOUCH_MIN + 8, 52)
        gap, pad = GAP, 14
        sheet_h = pad + 36 + 48 + 2 * (btn_h + gap) + pad
        sheet = pygame.Rect((self.size[0] - sheet_w) // 2,
                            (self.size[1] - sheet_h) // 2,
                            sheet_w, sheet_h)
        panel(self.surface, sheet, theme.BG, shadow=True, focus=True)
        head = pygame.Rect(sheet.x + pad, sheet.y + pad,
                           sheet.width - 2 * pad, 28)
        ver = remote.version or remote.short_commit() or "new"
        text(self.surface, f"UPDATE {ver}".upper(), head, 18, theme.TEXT,
             bold=True, display=True, align="left")
        notes = remote.notes or detail or "A newer Ranger Suite is available."
        if local.short_commit():
            notes = f"{notes}  (now {local.short_commit()})"
        body = pygame.Rect(sheet.x + pad, head.bottom + 4,
                           sheet.width - 2 * pad, 40)
        text(self.surface, notes[:90], body, 13, theme.TEXT_DIM, align="left")
        y = body.bottom + 8
        for key, label, kind in (
                ("update:install", "INSTALL", "prim"),
                ("update:later", "LATER", "neut")):
            rect = pygame.Rect(sheet.x + pad, y, sheet.width - 2 * pad, btn_h)
            button(self.surface, self.chrome, key, rect, label, 18, kind=kind)
            y += btn_h + gap

    def _draw_message(self) -> None:
        if not self._message or self.now_ms() > self._message_until:
            return
        # Toast / LCD voice — black well, cyan type (never a coloured bubble).
        rect = pygame.Rect(MARGIN + 8, self.size[1] - LEGEND_H - 34,
                           min(520, self.size[0] - 2 * MARGIN - 16), 28)
        toast(self.surface, rect, self._message)
