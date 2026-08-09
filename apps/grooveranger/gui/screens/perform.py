"""PERFORM — pads under the fingers, patterns under the thumb.

The 4×3 pad bank (tap to play, long-press to mute), the eight pattern
slots with queue tinting, FILL, record arm, the mute-group keys, and a
sixteen-cell playhead strip. On the wide bar the pads take the left
two-thirds; portrait stacks pads over the controls.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.steps import PADS
from gui.screens.base import Screen
from rangerkit import enginebase as base
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, column, grid, lcd, panel, row

STRIP_H = 22


class PerformScreen(Screen):
    title = "PERFORM"
    legend = "TAP a pad to hit it · HOLD a pad to mute the track"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("pad"):
            return [cmd.PadHit(pad=int(key[3:]))]
        if key.startswith("pt"):
            return [cmd.SelectPattern(index=int(key[2:]))]
        if key == "fill":
            return [cmd.QueueFill()]
        if key == "rec":
            return [base.SetRecord(on=not s.recording)]
        if key.startswith("mg"):
            return [cmd.MuteGroup(group=int(key[2:]))]
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("pad"):
            return [cmd.ToggleMute(pad=int(key[3:]))]
        return self.on_tap(key)

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-8, -8)
        if theme.is_wide(self.rect):
            pads_rect = pygame.Rect(inner.x, inner.y,
                                    inner.width * 13 // 20, inner.height)
            rail = pygame.Rect(pads_rect.right + 6, inner.y,
                               inner.right - pads_rect.right - 6,
                               inner.height)
        else:
            pads_rect = pygame.Rect(inner.x, inner.y, inner.width,
                                    inner.height * 11 // 20)
            rail = pygame.Rect(inner.x, pads_rect.bottom + 6, inner.width,
                               inner.bottom - pads_rect.bottom - 6)
        self._pads(surface, pads_rect, s)
        self._rail(surface, rail, s)

    def _pads(self, surface, rect, s) -> None:
        strip = pygame.Rect(rect.x, rect.y, rect.width, STRIP_H)
        for index, cell in enumerate(row(strip, 16, gap=2)):
            live = index == s.step_pos
            in_pattern = index < s.length
            face = theme.ACCENT if live else (
                theme.BG_SUNKEN if in_pattern else theme.BG)
            panel(surface, cell, face)
        bank = pygame.Rect(rect.x, strip.bottom + 4, rect.width,
                           rect.bottom - strip.bottom - 4)
        for index, cell in enumerate(grid(bank, 4, 3, gap=4)):
            if index >= PADS:
                break
            view = s.pads[index]
            key = f"pad{index}"
            # A muted pad dims; it does not turn red. Red is stop and delete,
            # and a wall of red pads made a perfectly ordinary arrangement
            # look like a rack full of faults.
            any_solo = any(p.soloed for p in s.pads)
            kind = ("solo" if view.soloed else
                    "mute" if view.muted or any_solo else "neut")
            button(surface, self.hits, key, cell, view.name, 15,
                   kind=kind,
                   active=kind != "neut" or bool(view.sounding),
                   color=theme.ACCENT if view.sounding else None,
                   pressed=self.is_pressed(key),
                   sub="muted" if view.muted else
                   ("solo" if view.soloed else
                    (f"g{view.group}" if view.group else "")))

    def _rail(self, surface, rect, s) -> None:
        rows = column(rect, 4, gap=5)
        # Pattern slots, two rows of four.
        for half, half_rect in enumerate(row(rows[0], 2, gap=4)):
            for quarter, cell in enumerate(row(half_rect, 4, gap=3)):
                index = half * 4 + quarter
                key = f"pt{index}"
                if index == s.pattern_index:
                    color = theme.ACCENT
                elif index == s.queued:
                    color = theme.ACCENT2
                elif s.patterns_used[index]:
                    color = theme.tint(theme.ACCENT2, 0.35)
                else:
                    color = None
                button(surface, self.hits, key, cell, f"{index + 1}", 14,
                       active=index in (s.pattern_index, s.queued),
                       color=color, pressed=self.is_pressed(key))
        controls = row(rows[1], 2, gap=4)
        button(surface, self.hits, "fill", controls[0],
               "FILL", 14, active=s.fill or s.fill_queued,
               color=theme.ACCENT2,
               sub="queued" if s.fill_queued else
               ("now" if s.fill else "next pass"))
        button(surface, self.hits, "rec", controls[1], "REC", 14,
               active=s.recording, color=theme.DANGER,
               sub="writing" if s.recording else "arm")
        groups = row(rows[2], 4, gap=3)
        for group in range(1, 5):
            members = [p for p in s.pads if p.group == group]
            all_muted = bool(members) and all(p.muted for p in members)
            button(surface, self.hits, f"mg{group}", groups[group - 1],
                   f"G{group}", 13, kind="mute", active=all_muted,
                   sub=f"{len(members)}" if members else "—")
        info = row(rows[3], 2, gap=4)
        lcd(surface, info[0], s.kit_name[:8].upper(), size=15, label="KIT")
        lcd(surface, info[1],
            f"{s.swing:.0%}" if s.swing > 0.5 else "OFF",
            size=15, label="SWING")
