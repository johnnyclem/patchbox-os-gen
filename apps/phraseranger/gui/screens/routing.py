"""ROUTING — each loop's plumbing and feel, one row per track.

Output, channel, loop ownership (locked to the global length or free),
reverse/stretch verbs, and the per-track feel (feedback, density,
humanize). Values live on the selected row; the verbs act immediately.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head
from rangerkit.routing import OUTPUTS

STEPPED = ("chan", "tbars", "feed", "dens", "hum")


class RoutingScreen(Screen):
    title = "ROUTING"
    legend = "TAP a destination to bind it · − / + step the feel"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._track = 0

    def _view(self):
        s = self.snapshot
        return s.tracks[self._track] if s and \
            self._track < len(s.tracks) else None

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        view = self._view()
        if key.startswith("sel"):
            self._track = int(key[3:])
            return []
        if view is None:
            return []
        index = self._track
        if key == "dest":
            return [cmd.SetTrackField(index=index, name="dest",
                                      value=cycle(OUTPUTS, view.dest))]
        if key == "locked":
            return [cmd.SetTrackField(index=index, name="length_locked",
                                      value=not view.length_locked)]
        if key == "reverse":
            return [cmd.ReverseTrack(index=index)]
        if key == "half":
            return [cmd.StretchTrack(index=index, factor=0.5)]
        if key == "double":
            return [cmd.StretchTrack(index=index, factor=2.0)]
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
        index = self._track
        if name == "chan":
            return [cmd.SetTrackField(index=index, name="channel",
                                      value=view.channel + direction)]
        if name == "tbars":
            return [cmd.SetTrackBars(index=index,
                                     bars=view.bars + direction)]
        if name == "feed":
            return [cmd.SetTrackField(
                index=index, name="feedback",
                value=round(view.feedback + 0.05 * direction, 2))]
        if name == "dens":
            return [cmd.SetTrackField(
                index=index, name="probability",
                value=round(view.probability + 0.05 * direction, 2))]
        if name == "hum":
            return [cmd.SetTrackField(
                index=index, name="humanize_timing",
                value=view.humanize_timing + direction)]
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "ROUTING + FEEL · THE SELECTED TRACK")
        strip_h = max(theme.TOUCH_MIN, inner.height // 6)
        strip = pygame.Rect(inner.x, inner.y + 20, inner.width, strip_h)
        for index, (view, cell) in enumerate(zip(
                s.tracks, row(strip, len(s.tracks), gap=4))):
            button(surface, self.hits, f"sel{index}", cell,
                   f"T{index + 1}", 13, active=index == self._track,
                   color=theme.ACCENT if view.notes else None,
                   sub=view.dest.replace("_out", ""))
        editor = pygame.Rect(inner.x, strip.bottom + 6, inner.width,
                             inner.bottom - strip.bottom - 6)
        view = self._view()
        if view is None:
            return
        wide = theme.is_wide(self.rect)
        columns = row(editor, 3, gap=8) if wide else column(editor, 3, gap=6)
        self._plumbing(surface, columns[0], view)
        self._length(surface, columns[1], view)
        self._feel(surface, columns[2], view)

    def _plumbing(self, surface, rect, view) -> None:
        cells = column(rect, 3, gap=5)
        button(surface, self.hits, "dest", cells[0],
               view.dest.replace("_", " "), 13, sub="output")
        Stepper("chan", "CHANNEL", str(view.channel + 1)).draw(
            surface, self.hits, cells[1], self._pressed)
        verbs = row(cells[2], 2, gap=5)
        button(surface, self.hits, "reverse", verbs[0], "REVERSE", 12,
               color=theme.ACCENT2)
        button(surface, self.hits, "half", verbs[1], "½×", 14,
               color=theme.ACCENT2, display=False)

    def _length(self, surface, rect, view) -> None:
        cells = column(rect, 3, gap=5)
        button(surface, self.hits, "locked", cells[0],
               "LOCKED" if view.length_locked else "FREE", 13,
               active=view.length_locked, color=theme.ACCENT,
               sub="global bars" if view.length_locked else "own bars")
        Stepper("tbars", "BARS", str(view.bars)).draw(
            surface, self.hits, cells[1], self._pressed)
        button(surface, self.hits, "double", cells[2], "2×", 14,
               color=theme.ACCENT2, sub="stretch")

    def _feel(self, surface, rect, view) -> None:
        cells = column(rect, 3, gap=5)
        Stepper("feed", "FEEDBACK", f"{view.feedback:.0%}").draw(
            surface, self.hits, cells[0], self._pressed)
        Stepper("dens", "DENSITY", f"{view.probability:.0%}").draw(
            surface, self.hits, cells[1], self._pressed)
        Stepper("hum", "HUMANIZE", f"{view.humanize_timing}t").draw(
            surface, self.hits, cells[2], self._pressed)
