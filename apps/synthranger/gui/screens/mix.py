"""MIX — four part strips and the mod matrix.

Each strip: level, pan, listen channel, polyphony, mute. Below, the
selected part's four mod slots — source ▸ destination × amount — the
routing that makes the XY pad and the wheel do anything at all.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.modmatrix import MOD_DESTS, MOD_SOURCES, SLOTS
from core.parts import PARTS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, \
    section_head

STEPPED = tuple(f"{name}{part}" for part in range(PARTS)
                for name in ("lvl", "pan", "chn", "ply")) \
    + tuple(f"amt{slot}" for slot in range(SLOTS))


class MixScreen(Screen):
    title = "MIX"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("sel"):
            return [cmd.SelectPart(part=int(key[3:]))]
        if key.startswith("mute"):
            part = int(key[4:])
            return [cmd.SetPartField(part=part, name="muted",
                                     value=not s.parts[part].muted)]
        if key.startswith("src") or key.startswith("dst"):
            slot = int(key[3:])
            mod = s.parts[s.selected_part].mods[slot]
            if key.startswith("src"):
                return [cmd.SetModSlot(
                    part=s.selected_part, slot=slot,
                    source=cycle(MOD_SOURCES, mod.source), dest=mod.dest,
                    amount=mod.amount)]
            return [cmd.SetModSlot(
                part=s.selected_part, slot=slot, source=mod.source,
                dest=cycle(MOD_DESTS, mod.dest), amount=mod.amount)]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        if name.startswith("amt"):
            slot = int(name[3:])
            mod = s.parts[s.selected_part].mods[slot]
            return [cmd.SetModSlot(
                part=s.selected_part, slot=slot, source=mod.source,
                dest=mod.dest,
                amount=round(mod.amount + 0.1 * direction, 2))]
        part = int(name[3:])
        view = s.parts[part]
        field, step = {"lvl": ("level", 0.05), "pan": ("pan", 0.1),
                       "chn": ("channel", 1), "ply": ("poly", 1)}[
            name[:3]]
        value = getattr(view, field) + step * direction
        if field in ("channel", "poly"):
            value = int(value)
        else:
            value = round(value, 3)
        return [cmd.SetPartField(part=part, name=field, value=value)]

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        wide = theme.is_wide(self.rect)
        halves = row(inner, 2, gap=10) if wide else column(inner, 2,
                                                           gap=6)
        self._strips(surface, halves[0], s)
        self._matrix(surface, halves[1], s)

    def _titled(self, surface, rect, label):
        section_head(surface, pygame.Rect(rect.x, rect.y, rect.width, 16),
                     label)
        return pygame.Rect(rect.x, rect.y + 18, rect.width,
                           rect.height - 18)

    def _strips(self, surface, rect, s) -> None:
        body = self._titled(surface, rect, "PARTS")
        for part, line in enumerate(column(body, PARTS, gap=4)):
            view = s.parts[part]
            cells = row(line, 6, gap=3)
            button(surface, self.hits, f"sel{part}", cells[0],
                   f"P{part + 1}", 12, active=part == s.selected_part,
                   color=theme.ACCENT if view.sounding else None,
                   sub=view.name[:6].lower())
            Stepper(f"lvl{part}", "LVL", f"{view.level:.2f}",
                    width=22).draw(surface, self.hits, cells[1],
                                   self._pressed, size=10)
            Stepper(f"pan{part}", "PAN", f"{view.pan:+.1f}",
                    width=22).draw(surface, self.hits, cells[2],
                                   self._pressed, size=10)
            Stepper(f"chn{part}", "CHAN", str(view.channel + 1),
                    width=22).draw(surface, self.hits, cells[3],
                                   self._pressed, size=10)
            Stepper(f"ply{part}", "POLY", str(view.poly),
                    width=22).draw(surface, self.hits, cells[4],
                                   self._pressed, size=10)
            button(surface, self.hits, f"mute{part}", cells[5],
                   "MUTED" if view.muted else "MUTE", 10,
                   active=view.muted, color=theme.DANGER)

    def _matrix(self, surface, rect, s) -> None:
        body = self._titled(surface, rect,
                            f"MOD MATRIX · P{s.selected_part + 1}")
        mods = s.parts[s.selected_part].mods
        for slot, line in enumerate(column(body, SLOTS, gap=4)):
            mod = mods[slot]
            cells = row(line, 3, gap=3)
            button(surface, self.hits, f"src{slot}", cells[0],
                   mod.source, 11, active=mod.source != "none",
                   color=theme.ACCENT2, sub="source")
            button(surface, self.hits, f"dst{slot}", cells[1],
                   mod.dest, 11, active=mod.dest != "none",
                   color=theme.ACCENT, sub="dest")
            Stepper(f"amt{slot}", "AMOUNT", f"{mod.amount:+.1f}",
                    width=26).draw(surface, self.hits, cells[2],
                                   self._pressed, size=11)
