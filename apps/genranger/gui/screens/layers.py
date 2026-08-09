"""LAYERS — the per-layer settings desk, and the key of the piece.

Six slots (dormant ones enable on tap), then the selected layer's identity:
role, algorithm, output, register, density, note length, step count, mute
and lock. The key header at the top retunes every layer at once.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.layers import ALGORITHMS, NOTE_LENGTHS, ROLES, STEP_COUNTS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head
from rangerkit.routing import OUTPUTS
from rangerkit.theory import SCALE_NAMES, note_name

STEPPED = ("chan", "dens", "octlo", "octhi", "root")


class LayersScreen(Screen):
    title = "LAYERS"
    legend = "TAP MUTE or LOCK · − / + step the layer's parameters"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._slot = 0

    def _view(self):
        s = self.snapshot
        if s is None or self._slot >= len(s.layers):
            return None
        return s.layers[self._slot]

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        view = self._view()
        if key.startswith("slot"):
            index = int(key[4:])
            if s and index < len(s.layers) and not s.layers[index].role:
                self._slot = index
                return [cmd.SetLayerField(index=index, name="enabled",
                                          value=True)]
            self._slot = index
            return []
        if view is None or not view.role:
            return []
        index = self._slot
        if key == "role":
            return [cmd.SetLayerField(index=index, name="role",
                                      value=cycle(ROLES, view.role))]
        if key == "algo":
            return [cmd.SetLayerField(index=index, name="algorithm",
                                      value=cycle(ALGORITHMS,
                                                  view.algorithm))]
        if key == "dest":
            return [cmd.SetLayerField(index=index, name="dest",
                                      value=cycle(OUTPUTS, view.dest))]
        if key == "len":
            return [cmd.SetLayerField(index=index, name="note_length",
                                      value=cycle(NOTE_LENGTHS,
                                                  view.note_length))]
        if key == "steps":
            return [cmd.SetLayerField(index=index, name="step_count",
                                      value=cycle(STEP_COUNTS,
                                                  view.step_count))]
        if key == "mute":
            return [cmd.ToggleLayerMute(index=index)]
        if key == "lock":
            return [cmd.ToggleLayerLock(index=index)]
        if key == "off":
            return [cmd.SetLayerField(index=index, name="enabled",
                                      value=False)]
        if key == "scale":
            return [cmd.SetKey(root=s.root,
                               scale=cycle(SCALE_NAMES, s.scale))]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        view = self._view()
        if name == "root":
            return [cmd.SetKey(root=(s.root + direction) % 12)]
        if view is None or not view.role:
            return []
        index = self._slot
        if name == "chan":
            return [cmd.SetLayerField(index=index, name="channel",
                                      value=view.channel + direction)]
        if name == "dens":
            return [cmd.SetLayerField(index=index, name="density",
                                      value=round(view.density
                                                  + 0.05 * direction, 2))]
        if name == "octlo":
            return [cmd.SetLayerField(index=index, name="octave_low",
                                      value=view.octave_low + direction)]
        if name == "octhi":
            return [cmd.SetLayerField(index=index, name="octave_high",
                                      value=view.octave_high + direction)]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "LAYERS · KEY")
        body = pygame.Rect(inner.x, inner.y + 20, inner.width,
                           inner.height - 20)
        key_h = max(theme.TOUCH_MIN, body.height // 6)
        key_rect = pygame.Rect(body.x, body.y, body.width, key_h)
        key_row = row(key_rect, 3, gap=6)
        Stepper("root", "ROOT", note_name(s.root)).draw(
            surface, self.hits, key_row[0], self._pressed)
        button(surface, self.hits, "scale", key_row[1], s.scale, 13,
               sub="scale")
        slots_rect = key_row[2]
        slots = row(slots_rect, len(s.layers), gap=3)
        for index, (view, cell) in enumerate(zip(s.layers, slots)):
            button(surface, self.hits, f"slot{index}", cell,
                   str(index + 1), 13, active=index == self._slot,
                   color=theme.ACCENT if view.role else None,
                   sub=view.role[:4] if view.role else "+")
        editor = pygame.Rect(body.x, key_rect.bottom + 6, body.width,
                             body.bottom - key_rect.bottom - 6)
        view = self._view()
        if view is None or not view.role:
            return
        wide = theme.is_wide(self.rect)
        columns = row(editor, 3, gap=8) if wide else column(editor, 3, gap=6)
        self._identity(surface, columns[0], view)
        self._register(surface, columns[1], view)
        self._state(surface, columns[2], view)

    def _identity(self, surface, rect, view) -> None:
        cells = column(rect, 4, gap=5)
        button(surface, self.hits, "role", cells[0], view.role, 14,
               sub="role")
        button(surface, self.hits, "algo", cells[1], view.algorithm, 14,
               sub="algorithm")
        button(surface, self.hits, "dest", cells[2],
               view.dest.replace("_", " "), 13, sub="output")
        Stepper("chan", "CHANNEL", str(view.channel + 1)).draw(
            surface, self.hits, cells[3], self._pressed)

    def _register(self, surface, rect, view) -> None:
        cells = column(rect, 4, gap=5)
        Stepper("dens", "DENSITY", f"{view.density:.0%}").draw(
            surface, self.hits, cells[0], self._pressed)
        Stepper("octlo", "OCT LOW", f"C{view.octave_low}").draw(
            surface, self.hits, cells[1], self._pressed)
        Stepper("octhi", "OCT HIGH", f"C{view.octave_high}").draw(
            surface, self.hits, cells[2], self._pressed)
        button(surface, self.hits, "len", cells[3], view.note_length, 13,
               sub="note length")

    def _state(self, surface, rect, view) -> None:
        cells = column(rect, 4, gap=5)
        button(surface, self.hits, "steps", cells[0],
               f"{view.step_count}", 14, sub="steps")
        button(surface, self.hits, "mute", cells[1],
               "MUTED" if view.muted else "MUTE", 14,
               kind="mute", active=view.muted)
        button(surface, self.hits, "lock", cells[2],
               "LOCKED" if view.locked else "LOCK", 14,
               active=view.locked, color=theme.DANGER)
        button(surface, self.hits, "off", cells[3], "REMOVE", 12,
               kind="dang", sub="disable slot")
