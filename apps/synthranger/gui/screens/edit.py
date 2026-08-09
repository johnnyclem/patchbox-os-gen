"""EDIT — the selected part's A patch, every number reachable.

Left: oscillator (engine, its character params) and filter (cutoff, res,
mode, env amount). Right: envelopes (amp + mod ADSR), LFO, and the part
effects. Edits go to patch A — morph position decides how much of them you
hear, and COPY▸B freezes the current sound as the morph target.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.dsp.oscillators import ENGINES
from core.dsp.tables import SHAPES
from core.patch import LFO_DESTS, LFO_SHAPES
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, \
    section_head

STEPPED = ("cut", "res", "fenv", "det", "rat", "idx", "pos", "warp",
           "aa", "ad", "as", "ar", "ma", "md", "ms", "mr",
           "lrate", "ldep", "drv", "cho", "dly")
_ENV_KEYS = {"aa": ("amp_env", 0), "ad": ("amp_env", 1),
             "as": ("amp_env", 2), "ar": ("amp_env", 3),
             "ma": ("mod_env", 0), "md": ("mod_env", 1),
             "ms": ("mod_env", 2), "mr": ("mod_env", 3)}


class EditScreen(Screen):
    title = "EDIT"
    legend = "TAP a page to open it · − / + step the selected parameter"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        patch = s.parts[s.selected_part].patch
        if key.startswith("part"):
            return [cmd.SelectPart(part=int(key[4:]))]
        if key == "engine":
            return self._field("engine", cycle(ENGINES, patch["engine"]))
        if key == "shape":
            return self._field("shape", cycle(SHAPES, patch["shape"]))
        if key == "fmode":
            return self._field("filter_mode",
                               "hp" if patch["filter_mode"] == "lp"
                               else "lp")
        if key == "ldest":
            return self._field("lfo_dest",
                               cycle(LFO_DESTS, patch["lfo_dest"]))
        if key == "lshape":
            return self._field("lfo_shape",
                               cycle(LFO_SHAPES, patch["lfo_shape"]))
        if key == "copyb":
            return [cmd.CopyAToB(part=s.selected_part)]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _field(self, name, value) -> list:
        s = self.snapshot
        return [cmd.SetPatchField(part=s.selected_part, name=name,
                                  value=value)]

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        patch = s.parts[s.selected_part].patch
        if name in _ENV_KEYS:
            field, slot = _ENV_KEYS[name]
            values = list(patch[field])
            step = 0.05 if slot == 2 else max(0.005, values[slot] * 0.2)
            values[slot] = round(values[slot] + step * direction, 4)
            return self._field(field, tuple(values))
        simple = {"cut": ("cutoff", 0.05), "res": ("resonance", 0.05),
                  "fenv": ("filter_env", 0.05),
                  "det": ("detune_cents", 1.0), "rat": ("fm_ratio", 0.25),
                  "idx": ("fm_index", 0.1), "pos": ("wt_position", 0.05),
                  "warp": ("pd_warp", 0.05), "lrate": ("lfo_rate", 0.2),
                  "ldep": ("lfo_depth", 0.05), "drv": ("drive", 0.05),
                  "cho": ("chorus", 0.05), "dly": ("delay_send", 0.05)}
        if name in simple:
            field, step = simple[name]
            return self._field(field,
                               round(patch[field] + step * direction, 4))
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        strip = pygame.Rect(inner.x, inner.y, inner.width,
                            max(theme.TOUCH_MIN, inner.height // 8))
        cells = row(strip, 6, gap=3)
        for index in range(4):
            view = s.parts[index]
            button(surface, self.hits, f"part{index}", cells[index],
                   f"P{index + 1}", 12, active=index == s.selected_part,
                   sub=view.name[:6].lower())
        button(surface, self.hits, "copyb", cells[4], "COPY▸B", 11,
               color=theme.ACCENT2, sub="freeze morph")
        button(surface, self.hits, "fmode", cells[5],
               s.parts[s.selected_part].patch["filter_mode"].upper(), 12,
               sub="filter mode")
        body = pygame.Rect(inner.x, strip.bottom + 6, inner.width,
                           inner.bottom - strip.bottom - 6)
        halves = row(body, 2, gap=10) if theme.is_wide(self.rect) \
            else column(body, 2, gap=6)
        self._voice(surface, halves[0], s)
        self._motion(surface, halves[1], s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)

    def _stepper(self, surface, cell, key, label, value, size=12,
                 width=28) -> None:
        Stepper(key, label, value, width=width).draw(
            surface, self.hits, cell, self._pressed, size=size)

    def _voice(self, surface, rect, s) -> None:
        patch = s.parts[s.selected_part].patch
        body = self._titled(surface, rect,
                            f"OSC + FILTER · {patch['name']}")
        lines = column(body, 3, gap=4)
        top = row(lines[0], 3, gap=4)
        button(surface, self.hits, "engine", top[0],
               patch["engine"].upper(), 13, color=theme.ACCENT,
               active=True, sub="engine")
        if patch["engine"] == "va":
            button(surface, self.hits, "shape", top[1], patch["shape"],
                   12, sub="shape")
            self._stepper(surface, top[2], "det", "DETUNE",
                          f"{patch['detune_cents']:.0f}c")
        elif patch["engine"] == "fm":
            self._stepper(surface, top[1], "rat", "RATIO",
                          f"{patch['fm_ratio']:.2f}")
            self._stepper(surface, top[2], "idx", "INDEX",
                          f"{patch['fm_index']:.1f}")
        elif patch["engine"] == "wavetable":
            self._stepper(surface, top[1], "pos", "POSITION",
                          f"{patch['wt_position']:.2f}")
            self._stepper(surface, top[2], "det", "DETUNE",
                          f"{patch['detune_cents']:.0f}c")
        else:
            self._stepper(surface, top[1], "warp", "WARP",
                          f"{patch['pd_warp']:.2f}")
            self._stepper(surface, top[2], "dly", "DELAY",
                          f"{patch['delay_send']:.2f}")
        mid = row(lines[1], 3, gap=4)
        self._stepper(surface, mid[0], "cut", "CUTOFF",
                      f"{patch['cutoff']:.2f}")
        self._stepper(surface, mid[1], "res", "RES",
                      f"{patch['resonance']:.2f}")
        self._stepper(surface, mid[2], "fenv", "F.ENV",
                      f"{patch['filter_env']:+.2f}")
        bottom = row(lines[2], 3, gap=4)
        self._stepper(surface, bottom[0], "drv", "DRIVE",
                      f"{patch['drive']:.2f}")
        self._stepper(surface, bottom[1], "cho", "CHORUS",
                      f"{patch['chorus']:.2f}")
        self._stepper(surface, bottom[2], "dly", "DELAY",
                      f"{patch['delay_send']:.2f}")

    def _motion(self, surface, rect, s) -> None:
        patch = s.parts[s.selected_part].patch
        body = self._titled(surface, rect, "ENVELOPES + LFO")
        lines = column(body, 3, gap=4)
        amp = row(lines[0], 4, gap=3)
        for cell, key, label, slot in (
                (amp[0], "aa", "A", 0), (amp[1], "ad", "D", 1),
                (amp[2], "as", "S", 2), (amp[3], "ar", "R", 3)):
            value = patch["amp_env"][slot]
            shown = f"{value:.2f}" if slot != 2 else f"{value:.0%}"
            self._stepper(surface, cell, key, f"AMP {label}", shown,
                          size=11, width=24)
        mod = row(lines[1], 4, gap=3)
        for cell, key, label, slot in (
                (mod[0], "ma", "A", 0), (mod[1], "md", "D", 1),
                (mod[2], "ms", "S", 2), (mod[3], "mr", "R", 3)):
            value = patch["mod_env"][slot]
            shown = f"{value:.2f}" if slot != 2 else f"{value:.0%}"
            self._stepper(surface, cell, key, f"MOD {label}", shown,
                          size=11, width=24)
        lfo = row(lines[2], 4, gap=3)
        self._stepper(surface, lfo[0], "lrate", "RATE",
                      f"{patch['lfo_rate']:.1f}", size=11, width=24)
        self._stepper(surface, lfo[1], "ldep", "DEPTH",
                      f"{patch['lfo_depth']:.2f}", size=11, width=24)
        button(surface, self.hits, "ldest", lfo[2],
               patch["lfo_dest"], 11,
               active=patch["lfo_dest"] != "none", color=theme.ACCENT3,
               sub="lfo dest")
        button(surface, self.hits, "lshape", lfo[3],
               patch["lfo_shape"], 11, sub="lfo shape")
