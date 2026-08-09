"""PERFORM — eight loops at a glance, one finger from a take.

The wide bar's showcase: one horizontal strip per track — ARM, MUTE, the
loop lane (note onsets + a moving playhead), UNDO — with quantize and the
global bar length above. Tap ARM on the armed track to land the take;
hold a strip to clear it.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, lcd, panel, \
    row, text

STEPPED = ("bars",)


class PerformScreen(Screen):
    title = "PERFORM"
    legend = "TAP a lane to select it · HOLD a lane to clear it"

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key == "quantize":
            return [cmd.SetQuantize(on=not s.quantize)]
        if key.startswith("arm"):
            index = int(key[3:])
            # Tapping the armed track's ARM lands the take (disarm).
            return [cmd.ArmTrack(index=-1 if index == s.armed else index)]
        if key.startswith("mute"):
            return [cmd.ToggleTrackMute(index=int(key[4:]))]
        if key.startswith("undo"):
            return [cmd.UndoTrack(index=int(key[4:]))]
        if key.startswith("lane"):
            return [cmd.SelectSliceSource(index=int(key[4:]))]
        if key.endswith(("+", "-")):
            direction = +1 if key.endswith("+") else -1
            if key[:-1] == "bars":
                return [cmd.SetGlobalBars(bars=s.global_bars + direction)]
        return []

    def on_long_press(self, key: str) -> list:
        if key.startswith("lane"):
            return [cmd.ClearTrack(index=int(key[4:]))]
        return self.on_tap(key)

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head_h = max(theme.TOUCH_MIN, inner.height // 8)
        head = pygame.Rect(inner.x, inner.y, inner.width, head_h)
        controls = row(head, 3, gap=6)
        button(surface, self.hits, "quantize", controls[0],
               "QUANTIZE", 13, active=s.quantize, color=theme.ACCENT,
               sub="1/16" if s.quantize else "free")
        Stepper("bars", "LOOP BARS", str(s.global_bars)).draw(
            surface, self.hits, controls[1], self._pressed)
        lcd(surface, controls[2],
            " ".join(str(n) for n in s.open_notes[:6]) or "—",
            size=13, label="RECORDER · HELD KEYS")
        body = pygame.Rect(inner.x, head.bottom + 6, inner.width,
                           inner.bottom - head.bottom - 6)
        strips = column(body, len(s.tracks), gap=4)
        for index, (view, strip) in enumerate(zip(s.tracks, strips)):
            self._strip(surface, strip, index, view)

    def _strip(self, surface, rect, index, view) -> None:
        controls_w = min(3 * (theme.TOUCH_MIN + 4), rect.width // 3)
        cell_w = controls_w // 3
        arm = pygame.Rect(rect.x, rect.y, cell_w - 2, rect.height)
        mute = pygame.Rect(rect.x + cell_w, rect.y, cell_w - 2, rect.height)
        undo = pygame.Rect(rect.x + cell_w * 2, rect.y, cell_w - 2,
                           rect.height)
        button(surface, self.hits, f"arm{index}", arm,
               "●", 15, active=view.armed, color=theme.ACCENT2,
               display=False)
        button(surface, self.hits, f"mute{index}", mute, "M", 13,
               kind="mute", active=view.muted)
        button(surface, self.hits, f"undo{index}", undo,
               f"↶{view.undo_depth}" if view.undo_depth else "↶", 12,
               display=False)
        lane = pygame.Rect(rect.x + controls_w + 4, rect.y,
                           rect.width - controls_w - 4, rect.height)
        face = theme.BG_SUNKEN if view.muted else theme.BG_RAISED
        panel(surface, lane, face)
        self.hits.add(f"lane{index}", lane)
        # Note onsets along the loop, then the playhead over them.
        for fraction in view.hits:
            x = lane.x + 2 + round(fraction * (lane.width - 6))
            mark = pygame.Rect(x, lane.y + 4, 3, lane.height - 8)
            surface.fill(theme.ACCENT, mark)
        x = lane.x + 2 + round(view.position * (lane.width - 6))
        surface.fill(theme.ACCENT2,
                     pygame.Rect(x, lane.y + 1, 2, lane.height - 2))
        caption = f"T{index + 1} · ch{view.channel + 1} · {view.bars}b" \
            + ("" if view.length_locked else " free") \
            + (f" · {view.notes}" if view.notes else " · empty")
        text(surface, caption, lane, 10,
             theme.TEXT_MUTED if view.muted else theme.TEXT_DIM,
             align="left")
