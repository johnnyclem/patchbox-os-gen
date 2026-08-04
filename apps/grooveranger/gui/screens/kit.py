"""KIT — the selected pad's voice, and the kit's plumbing.

Pad picker on top; below it the voice parameters (note, tune, filter, amp,
pan, sends, choke and mute group, mixer level) and the kit strip: previous /
next kit from the kit directories, destination and external channel.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.pad import CHOKE_GROUPS, MUTE_GROUPS
from core.steps import PADS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, lcd, row, \
    section_head
from rangerkit.routing import OUTPUTS

STEPPED = ("note", "tune", "filt", "amp", "pan", "dsend", "rsend",
           "choke", "grp", "lvl", "chan")
_DESTS = tuple(OUTPUTS)          # includes internal — the sampler


class KitScreen(Screen):
    title = "KIT"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("sel"):
            return [cmd.SelectPad(pad=int(key[3:]))]
        if key == "dest":
            return [cmd.SetKitField(name="dest",
                                    value=cycle(_DESTS, s.dest))]
        if key == "prevkit":
            self.host.load_kit_step(-1)
            return []
        if key == "nextkit":
            self.host.load_kit_step(+1)
            return []
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _pad_field(self, s, name, value) -> list:
        return [cmd.SetPadField(pad=s.selected_pad, name=name,
                                value=value)]

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        pad = s.pads[s.selected_pad]
        if name == "note":
            return self._pad_field(s, "note", pad.note + direction)
        if name == "tune":
            return self._pad_field(s, "tune",
                                   round(pad.tune + 0.5 * direction, 2))
        if name == "filt":
            return self._pad_field(s, "filter",
                                   round(pad.filter + 0.05 * direction, 3))
        if name == "amp":
            return self._pad_field(s, "amp",
                                   round(pad.amp + 0.05 * direction, 3))
        if name == "pan":
            return self._pad_field(s, "pan",
                                   round(pad.pan + 0.1 * direction, 2))
        if name == "dsend":
            return self._pad_field(
                s, "delay_send", round(pad.delay_send + 0.05 * direction,
                                       3))
        if name == "rsend":
            return self._pad_field(
                s, "reverb_send", round(pad.reverb_send + 0.05 * direction,
                                        3))
        if name == "choke":
            return self._pad_field(s, "choke",
                                   (pad.choke + direction)
                                   % (CHOKE_GROUPS + 1))
        if name == "grp":
            return self._pad_field(s, "group",
                                   (pad.group + direction)
                                   % (MUTE_GROUPS + 1))
        if name == "lvl":
            return [cmd.SetMixerLevel(
                pad=s.selected_pad,
                value=round(pad.level + 0.05 * direction, 3))]
        if name == "chan":
            return [cmd.SetKitField(name="channel",
                                    value=s.channel + direction)]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        pad_h = max(theme.TOUCH_MIN, inner.height // 7)
        pads = pygame.Rect(inner.x, inner.y, inner.width, pad_h)
        for index, cell in enumerate(row(pads, PADS, gap=2)):
            view = s.pads[index]
            button(surface, self.hits, f"sel{index}", cell,
                   view.name[:4], 10, active=index == s.selected_pad,
                   color=theme.ACCENT if view.sounding else None,
                   sub="" if view.has_samples else "midi")
        body = pygame.Rect(inner.x, pads.bottom + 6, inner.width,
                           inner.bottom - pads.bottom - 6)
        halves = row(body, 2, gap=10) if theme.is_wide(self.rect) \
            else column(body, 2, gap=6)
        self._voice(surface, halves[0], s)
        self._plumbing(surface, halves[1], s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)

    def _voice(self, surface, rect, s) -> None:
        pad = s.pads[s.selected_pad]
        body = self._titled(surface, rect, f"VOICE · {pad.name}")
        lines = column(body, 3, gap=4)
        top = row(lines[0], 3, gap=4)
        Stepper("note", "NOTE", str(pad.note), width=30).draw(
            surface, self.hits, top[0], self._pressed, size=12)
        Stepper("tune", "TUNE", f"{pad.tune:+.1f}", width=30).draw(
            surface, self.hits, top[1], self._pressed, size=12)
        Stepper("lvl", "LEVEL", f"{pad.level:.2f}", width=30).draw(
            surface, self.hits, top[2], self._pressed, size=12)
        mid = row(lines[1], 3, gap=4)
        Stepper("filt", "FILTER", f"{pad.filter:.2f}", width=30).draw(
            surface, self.hits, mid[0], self._pressed, size=12)
        Stepper("amp", "AMP", f"{pad.amp:.2f}", width=30).draw(
            surface, self.hits, mid[1], self._pressed, size=12)
        Stepper("pan", "PAN", f"{pad.pan:+.1f}", width=30).draw(
            surface, self.hits, mid[2], self._pressed, size=12)
        bottom = row(lines[2], 4, gap=4)
        Stepper("dsend", "DELAY", f"{pad.delay_send:.2f}",
                width=26).draw(surface, self.hits, bottom[0],
                               self._pressed, size=11)
        Stepper("rsend", "VERB", f"{pad.reverb_send:.2f}",
                width=26).draw(surface, self.hits, bottom[1],
                               self._pressed, size=11)
        Stepper("choke", "CHOKE",
                "—" if not pad.choke else f"c{pad.choke}",
                width=26).draw(surface, self.hits, bottom[2],
                               self._pressed, size=11)
        Stepper("grp", "GROUP",
                "—" if not pad.group else f"g{pad.group}",
                width=26).draw(surface, self.hits, bottom[3],
                               self._pressed, size=11)

    def _plumbing(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "KIT + ROUTING")
        lines = column(body, 3, gap=4)
        kits = row(lines[0], 3, gap=4)
        button(surface, self.hits, "prevkit", kits[0], "◂", 16,
               sub="kit")
        lcd(surface, kits[1], s.kit_name[:8].upper(), size=14, label="KIT")
        button(surface, self.hits, "nextkit", kits[2], "▸", 16,
               sub="kit")
        route = row(lines[1], 2, gap=4)
        button(surface, self.hits, "dest", route[0],
               s.dest.replace("_", " "), 13, sub="destination",
               active=s.dest_bound, color=theme.ACCENT)
        Stepper("chan", "EXT CHAN", str(s.channel + 1), width=34).draw(
            surface, self.hits, route[1], self._pressed, size=13)
        lcd(surface, lines[2],
            f"{s.voices} sounding · {s.backend}", size=12,
            label="ENGINE")
