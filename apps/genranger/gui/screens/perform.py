"""PERFORM — the evolution controls and the piece at a glance.

The stage view: cruise, mutate-now, lock-all, the three global amounts
(density, complexity, chaos), and one strip per layer — role, algorithm, a
step-position sweep, a lock LED. Tap a strip to mute it; hold it to mutate
just that layer.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, lcd, led, panel, \
    row, section_head, text

STEPPED = ("dens", "cplx", "chaos")


class PerformScreen(Screen):
    title = "PERFORM"
    legend = "TAP a layer to select it · HOLD a layer to mutate it now"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key == "cruise":
            return [cmd.SetCruise(on=not s.cruise_on)]
        if key == "mutate":
            return [cmd.MutateNow()]
        if key == "lockall":
            return [cmd.LockAll()]
        if key.startswith("layer"):
            return [cmd.ToggleLayerMute(index=int(key[5:]))]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("layer"):
            return [cmd.MutateNow(index=int(key[5:]))]
        return self.on_tap(key)

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        if name == "dens":
            return [cmd.SetMacro(name="density",
                                 value=round(s.macro_density
                                             + 0.05 * direction, 2))]
        if name == "cplx":
            return [cmd.SetMacro(name="complexity",
                                 value=round(s.macro_complexity
                                             + 0.05 * direction, 2))]
        if name == "chaos":
            return [cmd.SetCruiseField(name="chaos",
                                       value=round(s.chaos
                                                   + 0.05 * direction, 2))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            controls, layers = row(inner, 2, gap=10)
        else:
            controls, layers = column(inner, 2, gap=8)
        self._controls(surface, controls, s)
        self._layers(surface, layers, s)

    def _controls(self, surface, rect, s) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "EVOLUTION")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        cells = column(body, 5, gap=6)
        top = row(cells[0], 2, gap=5)
        button(surface, self.hits, "cruise", top[0], "CRUISE", 15,
               active=s.cruise_on, color=theme.ACCENT,
               sub="evolving" if s.cruise_on else "held")
        button(surface, self.hits, "mutate", top[1], "MUTATE", 15,
               color=theme.ACCENT2, sub="now",
               pressed=self.is_pressed("mutate"))
        Stepper("chaos", "CHAOS", f"{s.chaos:.0%}").draw(
            surface, self.hits, cells[1], self._pressed)
        Stepper("dens", "DENSITY", f"{s.macro_density:.0%}").draw(
            surface, self.hits, cells[2], self._pressed)
        Stepper("cplx", "COMPLEXITY", f"{s.macro_complexity:.0%}").draw(
            surface, self.hits, cells[3], self._pressed)
        bottom = row(cells[4], 2, gap=5)
        button(surface, self.hits, "lockall", bottom[0],
               "UNLOCK ALL" if s.all_locked else "LOCK ALL", 12,
               active=s.all_locked, color=theme.DANGER)
        lcd(surface, bottom[1],
            f"{len([v for v in s.layers if v.role])} layers",
            size=13, label=f"{s.scale.upper()} · GEN")

    def _layers(self, surface, rect, s) -> None:
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        section_head(surface, head, "LAYERS · TAP MUTE · HOLD MUTATE")
        body = pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)
        active = [(i, v) for i, v in enumerate(s.layers) if v.role]
        if not active:
            text(surface, "no layers", body, 13, theme.TEXT_MUTED)
            return
        strips = column(body, len(active), gap=5)
        for (index, view), strip in zip(active, strips):
            face = theme.BG_SUNKEN if view.muted else theme.BG_RAISED
            panel(surface, strip, face)
            self.hits.add(f"layer{index}", strip)
            name = pygame.Rect(strip.x + 6, strip.y, strip.width // 4,
                               strip.height)
            ink = theme.TEXT_MUTED if view.muted else theme.TEXT
            text(surface, f"{view.role} · {view.algorithm}", name, 12, ink,
                 display=True, align="left")
            # The step sweep: the pattern's hits with the playhead lit.
            lane = pygame.Rect(strip.x + strip.width // 4 + 8,
                               strip.centery - 8,
                               strip.width - strip.width // 4 - 60, 16)
            cols = max(1, view.step_count)
            for step in range(cols):
                cell = pygame.Rect(lane.x + step * lane.width // cols,
                                   lane.y,
                                   max(2, lane.width // cols - 2),
                                   lane.height)
                hit = step in view.hits
                here = step == view.current_step
                locked_step = view.lock_start <= step <= view.lock_end
                color = theme.ACCENT if hit else theme.BG_SUNKEN
                if here:
                    color = theme.ACCENT2
                elif locked_step and hit:
                    color = theme.tint(theme.DANGER, 0.5)
                surface.fill(color, cell)
            led(surface, (strip.right - 30, strip.centery),
                view.locked, color=theme.DANGER)
            led(surface, (strip.right - 14, strip.centery),
                bool(view.sounding), color=theme.ACCENT)
