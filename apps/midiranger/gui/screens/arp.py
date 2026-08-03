"""ARP — four slots, one deep editor.

The slot strip shows every arp's held notes at a glance; the editor below
works on the selected one. Input/output assignment is part of the editor
because "which keyboard drives which synth" *is* the arp's identity here,
not plumbing.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.arp import ANY_SOURCE, MAX_OCTAVES, MAX_RATCHET, OMNI, PATTERNS, \
    RATES
from gui.screens.base import Screen, cycle
from rangerkit.events import PPQN
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head, \
    text
from rangerkit.routing import INPUTS, OUTPUTS
from rangerkit.theory import note_label

SOURCES = (ANY_SOURCE,) + INPUTS
RATE_LABELS = {PPQN: "1/4", PPQN // 2: "1/8", PPQN // 3: "1/8T",
               PPQN // 4: "1/16", PPQN // 6: "1/16T", PPQN // 8: "1/32"}
STEPPED = ("chin", "chout", "gate", "oct", "ratch", "prob")


class ArpScreen(Screen):
    title = "ARP"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._slot = 0

    def _arp(self):
        s = self.snapshot
        return s.arps[self._slot] if s and self._slot < len(s.arps) else None

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        arp = self._arp()
        if key.startswith("slot"):
            self._slot = int(key[4:])
            return []
        if arp is None:
            return []
        index = self._slot
        if key == "on":
            return [cmd.SetArpField(index=index, name="enabled",
                                    value=not arp.enabled)]
        if key == "hold":
            return [cmd.SetArpField(index=index, name="hold",
                                    value=not arp.hold)]
        if key == "clear":
            return [cmd.ClearArp(index=index)]
        if key == "pattern":
            return [cmd.SetArpField(index=index, name="pattern",
                                    value=cycle(PATTERNS, arp.pattern))]
        if key == "rate":
            return [cmd.SetArpField(index=index, name="rate",
                                    value=cycle(RATES, arp.rate))]
        if key == "src":
            return [cmd.SetArpField(index=index, name="source",
                                    value=cycle(SOURCES, arp.source))]
        if key == "dest":
            return [cmd.SetArpField(index=index, name="dest",
                                    value=cycle(OUTPUTS, arp.dest))]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        arp = self._arp()
        if arp is None:
            return []
        index = self._slot
        if name == "chin":
            value = max(OMNI, min(15, arp.channel_in + direction))
            return [cmd.SetArpField(index=index, name="channel_in",
                                    value=value)]
        if name == "chout":
            return [cmd.SetArpField(index=index, name="channel_out",
                                    value=arp.channel_out + direction)]
        if name == "gate":
            return [cmd.SetArpField(index=index, name="gate",
                                    value=round(arp.gate + 0.05 * direction,
                                                2))]
        if name == "oct":
            value = max(1, min(MAX_OCTAVES, arp.octaves + direction))
            return [cmd.SetArpField(index=index, name="octaves", value=value)]
        if name == "ratch":
            value = max(1, min(MAX_RATCHET, arp.ratchet + direction))
            return [cmd.SetArpField(index=index, name="ratchet", value=value)]
        if name == "prob":
            return [cmd.SetArpField(
                index=index, name="probability",
                value=round(arp.probability + 0.05 * direction, 2))]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "ARPS · 4 INDEPENDENT")
        body = pygame.Rect(inner.x, inner.y + 20, inner.width,
                           inner.height - 20)
        strip_h = max(theme.TOUCH_MIN + 8, body.height // 5)
        strip = pygame.Rect(body.x, body.y, body.width, strip_h)
        editor = pygame.Rect(body.x, strip.bottom + 6, body.width,
                             body.bottom - strip.bottom - 6)
        for index, (arp, cell) in enumerate(zip(s.arps,
                                                row(strip, len(s.arps),
                                                    gap=6))):
            held = " ".join(note_label(n) for n in arp.held[:4]) \
                or ("latched" if arp.hold else "—")
            button(surface, self.hits, f"slot{index}", cell,
                   f"ARP {index + 1}", 14, active=index == self._slot,
                   color=theme.ACCENT if arp.enabled else None, sub=held)
        arp = self._arp()
        if arp is None:
            return
        wide = theme.is_wide(self.rect)
        columns = row(editor, 3, gap=8) if wide else column(editor, 3, gap=6)
        self._routing(surface, columns[0], arp)
        self._motion(surface, columns[1], arp)
        self._feel(surface, columns[2], arp)

    def _routing(self, surface, rect, arp) -> None:
        cells = column(rect, 4, gap=5)
        on_row = row(cells[0], 2, gap=5)
        button(surface, self.hits, "on", on_row[0],
               "ON" if arp.enabled else "OFF", 14, active=arp.enabled,
               color=theme.ACCENT)
        button(surface, self.hits, "clear", on_row[1], "CLEAR", 12,
               color=theme.DANGER)
        button(surface, self.hits, "src", cells[1],
               (arp.source or "any").replace("_", " "), 13, sub="input")
        Stepper("chin", "CH IN",
                "omni" if arp.channel_in == OMNI
                else str(arp.channel_in + 1)).draw(surface, self.hits,
                                                   cells[2], self._pressed)
        button(surface, self.hits, "dest", cells[3],
               arp.dest.replace("_", " "), 13, sub="output")

    def _motion(self, surface, rect, arp) -> None:
        cells = column(rect, 4, gap=5)
        button(surface, self.hits, "pattern", cells[0], arp.pattern, 14,
               sub="pattern")
        button(surface, self.hits, "rate", cells[1],
               RATE_LABELS.get(arp.rate, f"{arp.rate}t"), 14, sub="rate")
        Stepper("oct", "OCTAVES", str(arp.octaves)).draw(
            surface, self.hits, cells[2], self._pressed)
        Stepper("chout", "CH OUT", str(arp.channel_out + 1)).draw(
            surface, self.hits, cells[3], self._pressed)

    def _feel(self, surface, rect, arp) -> None:
        cells = column(rect, 4, gap=5)
        Stepper("gate", "GATE", f"{arp.gate:.0%}").draw(
            surface, self.hits, cells[0], self._pressed)
        Stepper("ratch", "RATCHET", str(arp.ratchet)).draw(
            surface, self.hits, cells[1], self._pressed)
        Stepper("prob", "PROB", f"{arp.probability:.0%}").draw(
            surface, self.hits, cells[2], self._pressed)
        button(surface, self.hits, "hold", cells[3],
               "HOLD", 14, active=arp.hold, color=theme.ACCENT2,
               sub="latch" if arp.hold else "off")
        if arp.held:
            text(surface, f"{len(arp.held)} held", rect, 10,
                 theme.TEXT_DIM, align="right")
