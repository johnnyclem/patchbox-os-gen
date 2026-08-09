"""ROUTING — each track's plumbing, and the selected clip's behavior.

Track strip: output + channel + mute. Below it, the clip inspector for the
selected slot: follow action, loop count, probability, velocity scale,
transpose — the launch behavior that makes a session self-playing.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.clip import FOLLOW_ACTIONS
from core.grid import TRACKS
from gui.screens.base import Screen, cycle
from rangerkit.gui import theme
from rangerkit.gui.widgets import Stepper, button, column, row, section_head, \
    text
from rangerkit.routing import OUTPUTS

STEPPED = ("chan", "loops", "prob", "vel", "trans", "slot")


class RoutingScreen(Screen):
    title = "ROUTING"
    legend = "TAP a destination to bind it · − / + step the channel"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._track = 0
        self._scene = 0

    def _clip_view(self):
        s = self.snapshot
        if s is None:
            return None
        return s.slots[self._track][self._scene]

    # --- input ----------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        s = self.snapshot
        if s is None:
            return []
        if key.startswith("sel"):
            self._track = int(key[3:])
            return []
        if key == "dest":
            view = s.tracks[self._track]
            return [cmd.SetTrackField(track=self._track, name="dest",
                                      value=cycle(OUTPUTS, view.dest))]
        if key == "mute":
            view = s.tracks[self._track]
            return [cmd.SetTrackField(track=self._track, name="muted",
                                      value=not view.muted)]
        if key == "follow":
            clip = self._clip_view()
            if clip and clip.filled:
                return [cmd.SetClipField(
                    track=self._track, scene=self._scene, name="follow",
                    value=cycle(FOLLOW_ACTIONS, clip.follow))]
            return []
        if key == "clearclip":
            return [cmd.ClearClip(track=self._track, scene=self._scene)]
        if key.endswith(("+", "-")):
            return self._step(key[:-1], +1 if key.endswith("+") else -1)
        return []

    def repeats(self, key: str) -> bool:
        return key[:-1] in STEPPED

    def on_repeat(self, key: str, steps: int) -> list:
        return self.on_tap(key) * steps

    def _clip_field(self, name, value) -> list:
        clip = self._clip_view()
        if clip is None or not clip.filled:
            return []
        return [cmd.SetClipField(track=self._track, scene=self._scene,
                                 name=name, value=value)]

    def _step(self, name: str, direction: int) -> list:
        s = self.snapshot
        if name == "slot":
            self._scene = (self._scene + direction) % len(
                s.slots[self._track])
            return []
        if name == "chan":
            view = s.tracks[self._track]
            return [cmd.SetTrackField(track=self._track, name="channel",
                                      value=view.channel + direction)]
        clip = self._clip_view()
        if clip is None or not clip.filled:
            return []
        if name == "loops":
            return self._clip_field("follow_loops",
                                    clip.follow_loops + direction)
        if name == "prob":
            return self._clip_field(
                "follow_probability",
                round(clip.follow_probability + 0.1 * direction, 2))
        if name == "vel":
            return self._clip_field(
                "velocity_scale",
                round(clip.velocity_scale + 0.05 * direction, 2))
        if name == "trans":
            return self._clip_field("transpose",
                                    clip.transpose + direction)
        return []

    # --- drawing ---------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        s = self.snapshot
        if s is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "ROUTING + CLIP BEHAVIOR")
        strip_h = max(theme.TOUCH_MIN, inner.height // 6)
        strip = pygame.Rect(inner.x, inner.y + 20, inner.width, strip_h)
        for index, (view, cell) in enumerate(zip(
                s.tracks, row(strip, TRACKS, gap=3))):
            button(surface, self.hits, f"sel{index}", cell,
                   str(index + 1), 12, active=index == self._track,
                   color=theme.ACCENT if view.active >= 0 else None)
        editor = pygame.Rect(inner.x, strip.bottom + 6, inner.width,
                             inner.bottom - strip.bottom - 6)
        wide = theme.is_wide(self.rect)
        columns = row(editor, 2, gap=8) if wide else column(editor, 2, gap=6)
        self._plumbing(surface, columns[0], s)
        self._inspector(surface, columns[1], s)

    def _plumbing(self, surface, rect, s) -> None:
        view = s.tracks[self._track]
        cells = column(rect, 3, gap=5)
        button(surface, self.hits, "dest", cells[0],
               view.dest.replace("_", " "), 13, sub="output")
        Stepper("chan", "CHANNEL", str(view.channel + 1)).draw(
            surface, self.hits, cells[1], self._pressed)
        button(surface, self.hits, "mute", cells[2],
               "MUTED" if view.muted else "MUTE", 13,
               kind="mute", active=view.muted)

    def _inspector(self, surface, rect, s) -> None:
        clip = self._clip_view()
        cells = column(rect, 3, gap=5)
        Stepper("slot", "CLIP SLOT",
                f"S{self._scene + 1}").draw(surface, self.hits, cells[0],
                                            self._pressed)
        if clip is None or not clip.filled:
            text(surface, "empty slot", cells[1], 12, theme.TEXT_MUTED)
            return
        follow_row = row(cells[1], 3, gap=4)
        button(surface, self.hits, "follow", follow_row[0],
               clip.follow, 12, sub="follow",
               active=clip.follow != "none", color=theme.ACCENT2)
        Stepper("loops", "LOOPS", str(clip.follow_loops),
                width=34).draw(surface, self.hits, follow_row[1],
                               self._pressed, size=12)
        Stepper("prob", "PROB", f"{clip.follow_probability:.0%}",
                width=34).draw(surface, self.hits, follow_row[2],
                               self._pressed, size=12)
        bottom = row(cells[2], 3, gap=4)
        Stepper("vel", "VEL", f"{clip.velocity_scale:.0%}",
                width=34).draw(surface, self.hits, bottom[0],
                               self._pressed, size=12)
        Stepper("trans", "TRANS", f"{clip.transpose:+d}",
                width=34).draw(surface, self.hits, bottom[1],
                               self._pressed, size=12)
        button(surface, self.hits, "clearclip", bottom[2], "CLEAR", 11,
               kind="dang",
               sub=f"{clip.bars}b · {clip.notes}n")
