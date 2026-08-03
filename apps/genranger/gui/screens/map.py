"""MAP — where the rules are touched.

The selected layer's material, editable: a probability lattice for grid
layers (tap a cell to cycle 0 → ½ → 1 → 0), the seed row and rule for
cellular layers, pulse/rotate steppers for euclid, temperature/style for
markov, interval leash for random. Below the editor, the lock-range strip:
first tap sets the range start, second the end, a tap inside clears it.

On the portrait panel the 16-step lattice pages in halves so every cell
keeps its 44 px.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.layers import GRID_ROWS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head, \
    text

STEPPED = ("pulses", "rot", "temp", "leash")


class MapScreen(Screen):
    title = "MAP"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._layer = 0
        self._page = 0
        self._range_start: int | None = None

    def _view(self):
        s = self.snapshot
        if s is None or self._layer >= len(s.layers):
            return None
        view = s.layers[self._layer]
        return view if view.role else None

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        view = self._view()
        if key.startswith("sel"):
            self._layer = int(key[3:])
            self._page = 0
            self._range_start = None
            return []
        if key == "page":
            self._page ^= 1
            return []
        if view is None:
            return []
        if key.startswith("g:"):
            _tag, step, grid_row = key.split(":")
            step, grid_row = int(step), int(grid_row)
            here = view.grid[grid_row][step] if view.grid else 0.0
            following = 0.5 if here < 0.25 else (1.0 if here < 0.75 else 0.0)
            return [cmd.SetGridCell(index=self._layer, step=step,
                                    row=grid_row, value=following)]
        if key.startswith("c:"):
            return [cmd.SetCaSeedCell(index=self._layer,
                                      cell=int(key[2:]))]
        if key.startswith("lr:"):
            step = int(key[3:])
            if view.lock_start <= step <= view.lock_end:
                self._range_start = None
                return [cmd.SetLockRange(index=self._layer, start=0,
                                         end=-1)]
            if self._range_start is None:
                self._range_start = step
                return [cmd.SetLockRange(index=self._layer, start=step,
                                         end=step)]
            start, self._range_start = self._range_start, None
            return [cmd.SetLockRange(index=self._layer,
                                     start=min(start, step),
                                     end=max(start, step))]
        if key == "style":
            return [cmd.SetLayerField(index=self._layer, name="style",
                                      value=cycle(("walk", "arpy", "drone",
                                                   "wander"), view.style))]
        if key == "rule":
            return [cmd.SetLayerField(index=self._layer, name="rule",
                                      value=cycle((30, 90, 110, 150, 182),
                                                  view.rule))]
        if key == "reseed":
            return [cmd.Reseed(index=self._layer)]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        view = self._view()
        if view is None:
            return []
        index = self._layer
        if name == "pulses":
            return [cmd.SetLayerField(index=index, name="pulses",
                                      value=view.pulses + direction)]
        if name == "rot":
            return [cmd.SetLayerField(index=index, name="rotate",
                                      value=view.rotate + direction)]
        if name == "temp":
            return [cmd.SetLayerField(
                index=index, name="temperature",
                value=round(view.temperature + 0.05 * direction, 2))]
        if name == "leash":
            return [cmd.SetLayerField(index=index, name="max_interval",
                                      value=view.max_interval + direction)]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "MAP · THE SELECTED LAYER'S RULES")
        body = pygame.Rect(inner.x, inner.y + 20, inner.width,
                           inner.height - 20)
        strip_h = max(theme.TOUCH_MIN + 4, body.height // 6)
        strip = pygame.Rect(body.x, body.y, body.width, strip_h)
        active = [(i, v) for i, v in enumerate(s.layers) if v.role]
        cells = row(strip, max(1, len(active)), gap=5)
        for (index, view), cell in zip(active, cells):
            button(surface, self.hits, f"sel{index}", cell,
                   f"L{index + 1}", 14, active=index == self._layer,
                   color=theme.ACCENT if not view.muted else None,
                   sub=view.algorithm)
        editor = pygame.Rect(body.x, strip.bottom + 6, body.width,
                             body.bottom - strip.bottom - 6)
        view = self._view()
        if view is None:
            text(surface, "select a layer", editor, 13, theme.TEXT_MUTED)
            return
        lock_h = theme.TOUCH_MIN
        material = pygame.Rect(editor.x, editor.y, editor.width,
                               editor.height - lock_h - 6)
        if view.algorithm == "grid":
            self._grid_editor(surface, material, view)
        elif view.algorithm == "cellular":
            self._ca_editor(surface, material, view)
        else:
            self._param_editor(surface, material, view)
        self._lock_strip(surface,
                         pygame.Rect(editor.x, material.bottom + 6,
                                     editor.width, lock_h), view)

    def _visible_steps(self, view) -> tuple[range, bool]:
        """Portrait pages the lattice in halves so cells keep 44 px."""
        wide = theme.is_wide(self.rect)
        if wide or view.step_count <= 8:
            return range(view.step_count), False
        half = view.step_count // 2
        start = self._page * half
        return range(start, start + half), True

    def _grid_editor(self, surface, rect, view) -> None:
        steps, paged = self._visible_steps(view)
        grid = view.grid or ()
        columns = len(steps) + (1 if paged else 0)
        for visual_row in range(GRID_ROWS):
            grid_row = GRID_ROWS - 1 - visual_row      # top = highest degree
            y = rect.y + visual_row * rect.height // GRID_ROWS
            height = rect.y + (visual_row + 1) * rect.height // GRID_ROWS - y
            for column_index, step in enumerate(steps):
                x = rect.x + column_index * rect.width // columns
                width = rect.x + (column_index + 1) * rect.width // columns \
                    - x
                cell = pygame.Rect(x + 1, y + 1, width - 3, height - 3)
                value = grid[grid_row][step] if grid else 0.0
                face = theme.blend(theme.BG_SUNKEN, theme.ACCENT,
                                   min(1.0, value))
                if step == view.current_step:
                    face = theme.blend(face, theme.ACCENT2, 0.35)
                surface.fill(face, cell)
                pygame.draw.rect(surface, theme.BORDER, cell, 1)
                self.hits.add(f"g:{step}:{grid_row}", cell)
        if paged:
            page_rect = pygame.Rect(rect.right - rect.width // columns + 2,
                                    rect.y, rect.width // columns - 2,
                                    rect.height)
            button(surface, self.hits, "page", page_rect,
                   "⇄", 16, sub=f"p{self._page + 1}")

    def _ca_editor(self, surface, rect, view) -> None:
        cells = column(rect, 3, gap=6)
        top = row(cells[0], 2, gap=6)
        button(surface, self.hits, "rule", top[0], f"RULE {view.rule}", 14,
               sub="tap to cycle")
        button(surface, self.hits, "reseed", top[1], "RESEED", 13,
               color=theme.ACCENT2)
        # The seed row, editable.
        seeds = row(cells[1].inflate(-4, -4), 16, gap=3)
        for bit, cell in enumerate(seeds):
            button(surface, self.hits, f"c:{bit}", cell, "", 10,
                   active=bool((view.ca_seed >> bit) & 1),
                   color=theme.ACCENT, display=False)
        # The evolving row, read-only.
        lane = cells[2].inflate(-4, -8)
        text(surface, f"gen {view.generation}", cells[2], 10,
             theme.TEXT_DIM, align="right")
        for bit, on in enumerate(view.ca_row or ()):
            cell = pygame.Rect(lane.x + bit * lane.width // 16, lane.y,
                               max(2, lane.width // 16 - 2), lane.height)
            surface.fill(theme.ACCENT if on else theme.BG_SUNKEN, cell)

    def _param_editor(self, surface, rect, view) -> None:
        cells = column(rect, 3, gap=6)
        if view.algorithm == "euclid":
            Stepper("pulses", "PULSES", str(view.pulses)).draw(
                surface, self.hits, cells[0], self._pressed)
            Stepper("rot", "ROTATE", str(view.rotate)).draw(
                surface, self.hits, cells[1], self._pressed)
        elif view.algorithm == "markov":
            button(surface, self.hits, "style", cells[0], view.style, 14,
                   sub="style")
            Stepper("temp", "TEMPERATURE",
                    f"{view.temperature:.0%}").draw(
                surface, self.hits, cells[1], self._pressed)
        else:
            Stepper("leash", "MAX INTERVAL",
                    str(view.max_interval)).draw(surface, self.hits,
                                                 cells[0], self._pressed)
        button(surface, self.hits, "reseed", cells[2], "RESEED", 13,
               color=theme.ACCENT2, sub="new material")

    def _lock_strip(self, surface, rect, view) -> None:
        steps, _paged = self._visible_steps(view)
        columns = max(1, len(steps))
        label = pygame.Rect(rect.x, rect.y - 14, rect.width, 12)
        text(surface, "LOCK RANGE — TAP START, TAP END, TAP INSIDE CLEARS",
             label, 9, theme.TEXT_DIM, display=True, align="left")
        for column_index, step in enumerate(steps):
            x = rect.x + column_index * rect.width // columns
            width = rect.x + (column_index + 1) * rect.width // columns - x
            cell = pygame.Rect(x + 1, rect.y, width - 3, rect.height)
            locked = view.lock_start <= step <= view.lock_end
            pending = self._range_start == step
            button(surface, self.hits, f"lr:{step}", cell,
                   "▪" if locked else "", 12,
                   active=locked or pending,
                   color=theme.DANGER, display=False)
