"""Test setup: put the app root on sys.path so ``core`` imports the way it
does under ``main.py``, and give the GUI tests a display that does not exist."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# SDL's dummy drivers let the GUI tests build real surfaces and run real event
# loops on a headless box. Set before pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
