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
from core.engine import GenRangerEngine                  # noqa: E402
from core.project import default_project                 # noqa: E402
from gui.app import App                                  # noqa: E402
from rangerkit import enginebase as base                 # noqa: E402
from rangerkit.events import TICKS_PER_BAR               # noqa: E402
from rangerkit.testkit import CaptureMidiIO, FakeClock   # noqa: E402


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") \
        else Path("docs/img")
    size = (1280, 400)
    for index, arg in enumerate(argv):
        if arg == "--size" and index + 1 < len(argv):
            width, _, height = argv[index + 1].partition("x")
            size = (int(width), int(height))
    out.mkdir(parents=True, exist_ok=True)

    project = default_project()
    # A fifth layer so the CA editor has something to show.
    project.params["layers"].append(
        {"role": "melody", "algorithm": "cellular", "dest": "din_out",
         "channel": 3, "rule": 110, "density": 0.6, "scale": "minor"})
    project.params["cruise"] = {"on": True, "speed": 0.9, "chaos": 0.5}
    engine = GenRangerEngine(project, CaptureMidiIO(), FakeClock())
    app = App(engine, size=size)
    # A demo state worth photographing: playing, evolved, seeds saved,
    # timeline populated, a lock range set.
    engine.submit(cmd.CaptureSeed(slot=0))
    engine.submit(cmd.CaptureSeed(slot=3))
    engine.submit(cmd.SetLockRange(index=0, start=4, end=7))
    engine.submit(base.Play())
    for _ in range(TICKS_PER_BAR * 5 + 40):
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
