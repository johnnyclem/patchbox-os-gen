"""Render every screen to PNG without a display.

    python bench/render_panel.py [outdir] [--size 1280x400]

Runs the real App against a real engine under SDL's dummy driver and writes
one image per tab. This is how the panel gets reviewed without the hardware
on the desk — and it is worth having as a script rather than a test because
looking at the pictures is the point.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(1, str(_ROOT.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame                                            # noqa: E402

from core import commands as cmd                         # noqa: E402
from core.clip import Clip, ClipNote                     # noqa: E402
from core.engine import SceneRangerEngine                # noqa: E402
from core.project import default_project                 # noqa: E402
from gui.app import App                                  # noqa: E402
from rangerkit.events import PPQN, TICKS_PER_BAR         # noqa: E402
from rangerkit.testkit import CaptureMidiIO, FakeClock   # noqa: E402


def make_clip(*pitches, bars=1, **fields):
    clip = Clip(length_ticks=bars * TICKS_PER_BAR, **fields).normalised()
    for index, pitch in enumerate(pitches):
        clip = clip.with_note(ClipNote(tick=index * PPQN, note=pitch,
                                       velocity=100, length_ticks=24))
    return clip


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") \
        else Path("docs/img")
    size = (1280, 400)
    for index, arg in enumerate(argv):
        if arg == "--size" and index + 1 < len(argv):
            width, _, height = argv[index + 1].partition("x")
            size = (int(width), int(height))
    out.mkdir(parents=True, exist_ok=True)

    engine = SceneRangerEngine(default_project(), CaptureMidiIO(),
                               FakeClock())
    app = App(engine, size=size)
    # A demo state worth photographing: a set in flight — clips across the
    # grid, a scene playing, one queued, a chain armed, a slot recording.
    engine.grid.put(0, 0, make_clip(36, 36, 42, 36, follow="again"))
    engine.grid.put(1, 0, make_clip(48, 55, bars=2))
    engine.grid.put(2, 0, make_clip(64, 67, 71))
    engine.grid.put(0, 1, make_clip(36, 42, follow="next"))
    engine.grid.put(3, 1, make_clip(72, bars=4))
    engine.grid.put(5, 2, make_clip(60))
    engine.submit(cmd.ChainAppend(scene=0, bars=4))
    engine.submit(cmd.ChainAppend(scene=1, bars=4))
    engine.submit(cmd.LaunchScene(scene=0))
    engine.submit(cmd.LaunchClip(track=3, scene=1))     # queued cross-scene
    for _ in range(TICKS_PER_BAR + PPQN + 8):
        engine.step()

    for index, screen in enumerate(app.screens):
        app.tab = index
        snapshot = engine.snapshot()
        screen.update(snapshot)
        app._draw(snapshot)
        path = out / (f"panel-{size[0]}x{size[1]}-{index}-"
                      f"{screen.title.lower()}.png")
        pygame.image.save(app.surface, str(path))
        print(f"wrote {path}")
    pygame.display.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
