"""Test setup: app root + apps/ on sys.path (so ``core`` and ``rangerkit``
import the way they do under main.py), and SDL pointed at a display that
does not exist."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for entry in (str(ROOT), str(ROOT.parent)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# SDL's dummy drivers let the GUI tests build real surfaces and run real event
# loops on a headless box. Set before pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
