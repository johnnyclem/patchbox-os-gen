"""Test setup: put ``apps/`` on sys.path so ``rangerkit`` imports the way it
does from an app, and give the GUI tests a display that does not exist."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APPS = Path(__file__).resolve().parent.parent.parent
if str(APPS) not in sys.path:
    sys.path.insert(0, str(APPS))

# SDL's dummy drivers let the GUI tests build real surfaces and run real event
# loops on a headless box. Set before pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
