"""FX — the thru rack: quantizer, harmonizer, note FX, and the LFO bank's
overview. Steppers ramp on hold; enums cycle on tap.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.cclfo import PERIODS, SHAPES
from core.harmonizer import MODES
from core.notefx import CURVES, MAX_TIMING
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head
from rangerkit.theory import SCALE_NAMES, note_name

STEPPED = ("root", "curveamt", "humtime", "humvel", "drop", "reps", "time",
           "decay")


class FxScreen(Screen):
    title = "FX"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._lfo = 0               # which LFO slot the strip edits

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key == "quant":
            return [cmd.SetQuantizerField(name="enabled",
                                          value=not s.quantizer_enabled)]
        if key == "scale":
            return [cmd.SetQuantizerField(
                name="scale", value=cycle(SCALE_NAMES, s.quantizer_scale))]
        if key == "harmony":
            return [cmd.SetHarmonizerField(
                name="mode", value=cycle(MODES, s.harmonizer_mode))]
        if key == "curve":
            return [cmd.SetFxField(name="curve",
                                   value=cycle(CURVES, s.fx_curve))]
        if key.startswith("lfosel"):
            self._lfo = int(key[6:])
            return []
        lfo = s.lfos[self._lfo] if self._lfo < len(s.lfos) else None
        if lfo is not None:
            if key == "lfoon":
                return [cmd.SetLfoField(index=self._lfo, name="enabled",
                                        value=not lfo.enabled)]
            if key == "lfoshape":
                return [cmd.SetLfoField(index=self._lfo, name="shape",
                                        value=cycle(SHAPES, lfo.shape))]
            if key == "lfoperiod":
                return [cmd.SetLfoField(index=self._lfo, name="period",
                                        value=cycle(PERIODS, lfo.period))]
        return self._step(key, +1) if key.endswith("+") else \
            self._step(key, -1) if key.endswith("-") else []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED or key[:-1] in ("lfocc", "lfodepth")

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps if self.repeats(key) else []

    def _step(self, key: str, direction: int) -> list:
        s = self.snapshot
        name = key[:-1]
        if name == "root":
            return [cmd.SetQuantizerField(
                name="root", value=(s.quantizer_root + direction) % 12)]
        if name == "curveamt":
            return [cmd.SetFxField(
                name="curve_amount",
                value=round(s.fx_curve_amount + 0.05 * direction, 2))]
        if name == "humtime":
            return [cmd.SetFxField(
                name="humanize_timing",
                value=min(MAX_TIMING, s.fx_humanize_timing + direction))]
        if name == "humvel":
            return [cmd.SetFxField(
                name="humanize_velocity",
                value=s.fx_humanize_velocity + 2 * direction)]
        if name == "drop":
            return [cmd.SetFxField(
                name="drop_probability",
                value=round(s.fx_drop_probability + 0.05 * direction, 2))]
        if name == "reps":
            return [cmd.SetFxField(name="echo_repeats",
                                   value=s.fx_echo_repeats + direction)]
        if name == "time":
            return [cmd.SetFxField(name="echo_ticks",
                                   value=s.fx_echo_ticks + 12 * direction)]
        if name == "decay":
            return [cmd.SetFxField(
                name="echo_decay",
                value=round(s.fx_echo_decay + 0.05 * direction, 2))]
        lfo = s.lfos[self._lfo] if self._lfo < len(s.lfos) else None
        if lfo is None:
            return []
        if name == "lfocc":
            return [cmd.SetLfoField(index=self._lfo, name="cc",
                                    value=lfo.cc + direction)]
        if name == "lfodepth":
            return [cmd.SetLfoField(index=self._lfo, name="depth",
                                    value=round(lfo.depth + 0.05 * direction,
                                                2))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        if theme.is_wide(self.rect):
            harmony_col, feel_col, lfo_col = row(inner, 3, gap=10)
        else:
            harmony_col, feel_col, lfo_col = column(inner, 3, gap=8)
        self._harmony(surface, harmony_col, s)
        self._feel(surface, feel_col, s)
        self._lfos(surface, lfo_col, s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 18),
                     label)
        return pygame.Rect(rect.x, rect.y + 20, rect.width, rect.height - 20)

    def _harmony(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "PITCH · QUANTIZE + HARMONIZE")
        cells = column(body, 4, gap=6)
        button(surface, self.hits, "quant", cells[0],
               "QUANTIZE", 14, active=s.quantizer_enabled,
               color=theme.ACCENT,
               sub="on" if s.quantizer_enabled else "off")
        Stepper("root", "ROOT",
                note_name(s.quantizer_root)).draw(surface, self.hits,
                                                  cells[1], self._pressed)
        button(surface, self.hits, "scale", cells[2], s.quantizer_scale, 13,
               sub="scale")
        button(surface, self.hits, "harmony", cells[3],
               s.harmonizer_mode, 14,
               active=s.harmonizer_mode != "off", color=theme.ACCENT2,
               sub="harmonizer")

    def _feel(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "FEEL · CURVE + HUMANIZE + ECHO")
        cells = column(body, 6, gap=5)
        curve_row = row(cells[0], 2, gap=5)
        button(surface, self.hits, "curve", curve_row[0], s.fx_curve, 13,
               sub="velocity")
        Stepper("curveamt", "AMT",
                f"{s.fx_curve_amount:.2f}").draw(surface, self.hits,
                                                 curve_row[1], self._pressed)
        Stepper("humtime", "HUM TIME",
                f"{s.fx_humanize_timing}t").draw(surface, self.hits,
                                                 cells[1], self._pressed)
        Stepper("humvel", "HUM VEL",
                f"±{s.fx_humanize_velocity}").draw(surface, self.hits,
                                                   cells[2], self._pressed)
        Stepper("drop", "DROP",
                f"{s.fx_drop_probability:.0%}").draw(surface, self.hits,
                                                     cells[3], self._pressed)
        echo_row = row(cells[4], 2, gap=5)
        Stepper("reps", "ECHO",
                str(s.fx_echo_repeats)).draw(surface, self.hits, echo_row[0],
                                             self._pressed)
        Stepper("time", "TIME",
                f"{s.fx_echo_ticks}t").draw(surface, self.hits, echo_row[1],
                                            self._pressed)
        Stepper("decay", "DECAY",
                f"{s.fx_echo_decay:.2f}").draw(surface, self.hits, cells[5],
                                               self._pressed)

    def _lfos(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "CC LFO BANK")
        cells = column(body, 5, gap=5)
        slots = row(cells[0], len(s.lfos), gap=4)
        for index, (lfo, slot) in enumerate(zip(s.lfos, slots)):
            button(surface, self.hits, f"lfosel{index}", slot,
                   str(index + 1), 15, active=index == self._lfo,
                   color=theme.ACCENT if lfo.enabled else None)
        lfo = s.lfos[self._lfo] if self._lfo < len(s.lfos) else None
        if lfo is None:
            return
        on_row = row(cells[1], 2, gap=5)
        button(surface, self.hits, "lfoon", on_row[0],
               "ON" if lfo.enabled else "OFF", 14, active=lfo.enabled,
               color=theme.ACCENT)
        button(surface, self.hits, "lfoshape", on_row[1], lfo.shape, 13,
               sub="shape")
        Stepper("lfocc", "CC", str(lfo.cc)).draw(surface, self.hits,
                                                 cells[2], self._pressed)
        Stepper("lfodepth", "DEPTH",
                f"{lfo.depth:.2f}").draw(surface, self.hits, cells[3],
                                         self._pressed)
        button(surface, self.hits, "lfoperiod", cells[4],
               f"{lfo.period}t", 13, sub="period")
