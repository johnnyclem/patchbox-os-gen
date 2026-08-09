"""PERFORM — activity, scenes, and the two hands-on controls.

The stage view: per-jack in/out activity, the eight scene pads (tap recalls,
long-press saves), the bypass switch, and what the pots are currently bound
to. Everything else lives one tab away.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.scene import SLOTS
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, grid, lcd, meter, panel, \
    row, section_head, text

ACTIVITY_SPAN = 24.0            # counts that light a meter fully


class PerformScreen(Screen):
    title = "PERFORM"
    legend = "TAP a scene to recall it · HOLD a scene to save over it"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._last_counts: dict = {}
        self._levels: dict = {}

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        if key.startswith("scene"):
            return [cmd.RecallScene(slot=int(key[5:]))]
        if key == "bypass":
            return [cmd.SetBypass(on=not self.snapshot.bypass)] \
                if self.snapshot else []
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("scene"):
            self.host.message(f"SCENE {int(key[5:]) + 1} SAVED")
            return [cmd.SaveScene(slot=int(key[5:]))]
        return self.on_tap(key)

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        snapshot = self.snapshot
        if snapshot is None:
            return
        inner = self.rect.inflate(-12, -12)
        wide = theme.is_wide(self.rect)
        if wide:
            left, middle, right = row(inner, 3, gap=10)
        else:
            left, middle, right = column(inner, 3, gap=8)
        self._draw_activity(surface, left, snapshot)
        self._draw_scenes(surface, middle, snapshot)
        self._draw_hot(surface, right, snapshot)

    def _decay(self, key: str, count: int) -> float:
        """Counts arrive as totals; the meter shows recent motion. A simple
        leaky peak: jumps light it, silence drains it."""
        delta = count - self._last_counts.get(key, count)
        self._last_counts[key] = count
        level = max(self._levels.get(key, 0.0) * 0.9,
                    min(1.0, delta / ACTIVITY_SPAN))
        self._levels[key] = level
        return level

    def _draw_activity(self, surface, rect, snapshot) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "MIDI ACTIVITY")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width,
                           rect.height - 20)
        lanes = list(snapshot.activity_in) + list(snapshot.activity_out)
        if not lanes:
            text(surface, "no routes", body, 13, theme.TEXT_MUTED)
            return
        cells = column(body, max(1, len(lanes)), gap=4)
        bound = dict(snapshot.inputs_bound) | dict(snapshot.outputs_bound)
        for (endpoint, count), cell in zip(lanes, cells):
            panel(surface, cell, theme.BG_RAISED)
            name = pygame.Rect(cell.x + 4, cell.y, cell.width // 2 - 4,
                               cell.height)
            ink = theme.TEXT if bound.get(endpoint) else theme.TEXT_MUTED
            text(surface, endpoint.replace("_", " "), name, 12, ink,
                 display=True, align="left")
            well = pygame.Rect(cell.centerx, cell.centery - 5,
                               cell.width // 2 - 8, 10)
            meter(surface, well, self._decay(endpoint, count))

    def _draw_scenes(self, surface, rect, snapshot) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "SCENES · TAP RECALL · HOLD SAVE")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        pads = grid(body, 2, SLOTS // 2, gap=6)
        morph = snapshot.morph
        for slot, pad in enumerate(pads):
            used = snapshot.scenes_occupied[slot]
            current = bool(morph) and morph[0] == slot
            button(surface, self.hits, f"scene{slot}", pad,
                   f"S{slot + 1}", 16,
                   active=current, pressed=self.is_pressed(f"scene{slot}"),
                   color=theme.ACCENT if used else None,
                   sub="" if used else "empty")

    def _draw_hot(self, surface, rect, snapshot) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "HOT CONTROLS")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        cells = column(body, 4, gap=6)
        button(surface, self.hits, "bypass", cells[0],
               "BYPASS" if not snapshot.bypass else "BYPASSED", 15,
               active=snapshot.bypass, color=theme.DANGER)
        pots = {str(k).upper(): v for k, v in snapshot.pots_map.items()}
        lcd(surface, cells[1], pots.get("POT_A", "arp_probability"),
            size=13, label="POT A")
        lcd(surface, cells[2], pots.get("POT_B", "humanize"),
            size=13, label="POT B")
        if snapshot.morph:
            a, b, t = snapshot.morph
            lcd(surface, cells[3], f"S{a + 1}→S{b + 1} {t:.0%}", size=15,
                label="MORPH")
        else:
            lcd(surface, cells[3], snapshot.project_name[:12], size=15,
                label="PROJECT")
