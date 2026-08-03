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
from core.engine import GrooveRangerEngine               # noqa: E402
from core.project import default_project                 # noqa: E402
from core.sequencer import STEP_TICKS                    # noqa: E402
from gui.app import App                                  # noqa: E402
from rangerkit import enginebase as base                 # noqa: E402
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

    engine = GrooveRangerEngine(default_project(), CaptureMidiIO(),
                                FakeClock())
    app = App(engine, size=size)
    # A demo state worth photographing: a beat in flight — ratchets and
    # locks on the grid, a queued pattern, a song chain armed, swing on,
    # one pad muted, the bus coloring the mix.
    engine.submit(cmd.SetStepField(pad=4, step=6, name="ratchet", value=3))
    engine.submit(cmd.ToggleStep(pad=2, step=12))
    engine.submit(cmd.SetStepLock(pad=2, step=12, name="tune", value=-5.0))
    engine.submit(cmd.SetStepField(pad=0, step=8, name="prob", value=0.6))
    engine.submit(cmd.ToggleStep(pad=11, step=2))
    engine.submit(cmd.ToggleMute(pad=3))
    engine.submit(cmd.SetSwing(value=0.57))
    engine.submit(cmd.ChainAppend(pattern=0, passes=4))
    engine.submit(cmd.ChainAppend(pattern=1, passes=2))
    engine.submit(cmd.SetMasterField(name="reverb", value=0.4))
    engine.submit(base.Play())
    for _ in range(STEP_TICKS * 5 + 3):
        engine.step()
    engine.submit(cmd.SelectPattern(index=1))
    engine.submit(cmd.QueueFill())
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
