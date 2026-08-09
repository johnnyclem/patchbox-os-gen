"""SEQ — the grid, one row at a time, with the whole tracker toolbox.

Pick a pad, toggle its sixteen steps, then lean on the selected step:
velocity, probability, ratchet, condition, micro-timing and the three
parameter locks. Row tools apply euclid, clear, and set pattern length and
swing. A long press on a step cell selects it without toggling.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.steps import CONDITIONS, PADS, PLOCK_NAMES, STEPS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, param, \
    row, section_head

STEPPED = ("vel", "prob", "rat", "mic", "len", "swg", "pls",
           "ltune", "lfilt", "lpan")
_LOCK_KEYS = {"ltune": "tune", "lfilt": "filter", "lpan": "pan"}
_LOCK_STEP = {"tune": 1.0, "filter": 0.1, "pan": 0.25}
_LOCK_START = {"tune": 0.0, "filter": 1.0, "pan": 0.0}
_LOCK_LO = {"tune": -12.0, "filter": 0.0, "pan": -1.0}
_LOCK_HI = {"tune": 12.0, "filter": 1.0, "pan": 1.0}


class SeqScreen(Screen):
    title = "SEQ"
    legend = ("TAP a step to toggle it · "
              "HOLD a step to select without toggling · "
              "HOLD a track chip to solo it")

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._step = 0
        self._pulses = 4

    def _sel(self):
        s = self.snapshot
        if s is None:
            return None
        return s.pattern[s.selected_pad][self._step]

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("sel"):
            return [cmd.SelectPad(pad=int(key[3:]))]
        if key.startswith("st"):
            self._step = int(key[2:])
            return [cmd.ToggleStep(pad=s.selected_pad, step=self._step)]
        if key == "cond":
            step = self._sel()
            return [cmd.SetStepField(pad=s.selected_pad, step=self._step,
                                     name="cond",
                                     value=cycle(CONDITIONS, step.cond))]
        if key == "clr":
            return [cmd.SetStepLock(pad=s.selected_pad, step=self._step,
                                    name=name, value=None)
                    for name in PLOCK_NAMES]
        if key == "row":
            return [cmd.ClearRow(pad=s.selected_pad)]
        if key == "euc":
            return [cmd.ApplyEuclid(pad=s.selected_pad,
                                    pulses=self._pulses)]
        if key.endswith(("+", "-")):
            return self._step_key(key[:-1],
                                  +1 if key.endswith("+") else -1)
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("st"):
            self._step = int(key[2:])       # select without toggling
            return []
        if key.startswith("sel"):
            # Solo. The engine has had ToggleSolo since it was written, but
            # no control ever emitted it, so the feature was unreachable from
            # the panel. Long-press is where the design system puts secondary
            # actions, and the pad chip is the thing you would press.
            return [cmd.ToggleSolo(pad=int(key[3:]))]
        return self.on_tap(key)

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _field(self, name, value) -> list:
        s = self.snapshot
        return [cmd.SetStepField(pad=s.selected_pad, step=self._step,
                                 name=name, value=value)]

    def _step_key(self, name: str, direction: int) -> list:
        s = self.snapshot
        step = self._sel()
        if name == "vel":
            return self._field("vel", step.vel + 5 * direction)
        if name == "prob":
            return self._field("prob", round(step.prob + 0.1 * direction,
                                             2))
        if name == "rat":
            return self._field("ratchet", step.ratchet + direction)
        if name == "mic":
            return self._field("micro", step.micro + direction)
        if name == "len":
            return [cmd.SetPatternLength(steps=s.length + direction)]
        if name == "swg":
            return [cmd.SetSwing(value=round(s.swing + 0.01 * direction,
                                             3))]
        if name == "pls":
            self._pulses = max(0, min(STEPS, self._pulses + direction))
            return []
        if name in _LOCK_KEYS:
            lock = _LOCK_KEYS[name]
            held = dict(step.locks).get(lock)
            value = (_LOCK_START[lock] if held is None else held) \
                + _LOCK_STEP[lock] * direction
            value = max(_LOCK_LO[lock], min(_LOCK_HI[lock], value))
            return [cmd.SetStepLock(pad=s.selected_pad, step=self._step,
                                    name=lock, value=round(value, 3))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        wide = theme.is_wide(self.rect)
        pad_h = max(theme.TOUCH_MIN, inner.height // 7)
        pads = pygame.Rect(inner.x, inner.y, inner.width, pad_h)
        for index, cell in enumerate(row(pads, PADS, gap=2)):
            view = s.pads[index]
            # Three orthogonal things on one chip, so each gets its own
            # channel: solo is a green face, mute is a dimmed one, and
            # selection is the cyan rule. Drawing any two of them as a
            # coloured fill made them the same shape at arm's length.
            # Once anything is soloed the rest dim, which is the only way to
            # see at a glance that a silent pad is silent *because* of solo.
            any_solo = any(p.soloed for p in s.pads)
            kind = ("solo" if view.soloed else
                    "mute" if view.muted or any_solo else "neut")
            button(surface, self.hits, f"sel{index}", cell,
                   view.name[:4], 10, kind=kind, active=kind != "neut",
                   focus=index == s.selected_pad)
        steps_h = max(theme.TOUCH_MIN + 8, inner.height // 4)
        steps_rect = pygame.Rect(inner.x, pads.bottom + 5, inner.width,
                                 steps_h)
        view_row = s.pattern[s.selected_pad]
        for index, cell in enumerate(row(steps_rect, STEPS, gap=2)):
            step = view_row[index]
            key = f"st{index}"
            if index >= s.length:
                color = None
            elif step.on and step.locks:
                color = theme.ACCENT3
            elif step.on:
                color = theme.ACCENT
            elif index == s.step_pos:
                color = theme.ACCENT2
            else:
                color = None
            marks = ""
            if step.on:
                if step.ratchet > 1:
                    marks += "≡"
                if step.cond != "always":
                    marks += "?"
                if step.micro:
                    marks += "±"
            button(surface, self.hits, key, cell,
                   marks or ("•" if step.on else ""), 13,
                   active=step.on or index == self._step,
                   color=color, pressed=self.is_pressed(key),
                   sub=f"{index + 1}" if index % 4 == 0 else "")
        editor = pygame.Rect(inner.x, steps_rect.bottom + 6, inner.width,
                             inner.bottom - steps_rect.bottom - 6)
        halves = row(editor, 2, gap=10) if wide \
            else column(editor, 2, gap=6)
        self._step_editor(surface, halves[0], s)
        self._row_tools(surface, halves[1], s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)

    def _step_editor(self, surface, rect, s) -> None:
        step = self._sel()
        body = self._titled(surface, rect,
                            f"STEP {self._step + 1} · "
                            f"{s.pads[s.selected_pad].name}")
        lines = column(body, 3, gap=4)
        top = row(lines[0], 2, gap=4)
        Stepper("vel", "VEL", str(step.vel), width=36).draw(
            surface, self.hits, top[0], self._pressed, size=13)
        Stepper("prob", "PROB", f"{step.prob:.0%}", width=36).draw(
            surface, self.hits, top[1], self._pressed, size=13)
        mid = row(lines[1], 3, gap=4)
        Stepper("rat", "RATCH", f"×{step.ratchet}", width=30).draw(
            surface, self.hits, mid[0], self._pressed, size=12)
        Stepper("mic", "MICRO", f"{step.micro:+d}", width=30).draw(
            surface, self.hits, mid[1], self._pressed, size=12)
        button(surface, self.hits, "cond", mid[2], step.cond, 12,
               active=step.cond != "always", color=theme.ACCENT2,
               sub="cond")
        locks = dict(step.locks)
        bottom = row(lines[2], 4, gap=4)
        Stepper("ltune", "TUNE",
                "—" if "tune" not in locks else
                f"{locks['tune']:+.0f}", width=28).draw(
            surface, self.hits, bottom[0], self._pressed, size=12)
        Stepper("lfilt", "FILT",
                "—" if "filter" not in locks else
                f"{locks['filter']:.1f}", width=28).draw(
            surface, self.hits, bottom[1], self._pressed, size=12)
        Stepper("lpan", "PAN",
                "—" if "pan" not in locks else
                f"{locks['pan']:+.2f}", width=28).draw(
            surface, self.hits, bottom[2], self._pressed, size=12)
        button(surface, self.hits, "clr", bottom[3], "CLR", 12,
               kind="dang", sub="locks")

    def _row_tools(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "ROW + PATTERN")
        lines = column(body, 3, gap=4)
        top = row(lines[0], 2, gap=4)
        Stepper("pls", "PULSES", str(self._pulses), width=36).draw(
            surface, self.hits, top[0], self._pressed, size=13)
        button(surface, self.hits, "euc", top[1], "EUCLID", 13,
               sub=f"{self._pulses}/{s.length}")
        mid = row(lines[1], 2, gap=4)
        Stepper("len", "LENGTH", f"{s.length}", width=36).draw(
            surface, self.hits, mid[0], self._pressed, size=13)
        Stepper("swg", "SWING", f"{s.swing:.0%}", width=36).draw(
            surface, self.hits, mid[1], self._pressed, size=13)
        # CLEAR ROW is destructive, so it is red — and a red control that also
        # happens to be the widest thing on the screen reads as the primary
        # action, which is the last thing a row-wipe should look like. Half the
        # line, with a count of what it would take beside it: the readout
        # answers "how much am I about to lose?" without a confirm dialog,
        # which an instrument panel has no room for anyway.
        tail = row(lines[2], 2, gap=4)
        live = sum(1 for step in s.pattern[s.selected_pad][:s.length]
                   if step.on)
        param(surface, tail[0], "STEPS ON", f"{live}/{s.length}", size=13)
        button(surface, self.hits, "row", tail[1], "CLEAR ROW", 13,
               kind="dang",
               sub=s.pads[s.selected_pad].name.lower())
