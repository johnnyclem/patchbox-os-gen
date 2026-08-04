"""Re-export shim — chord parsing and spelling now lives in rangerkit.

ChordRanger was the donor: this module's contents moved into
``rangerkit.chords`` when the suite grew siblings (RANGER-SUITE-PLAN
Phase 0) and came back home as a shim in Phase 7. Replacing the module in
``sys.modules`` aliases it completely — every ``from core.chords import X``
in the app and its tests resolves against the shared code, so there is
exactly one copy of these rules in the repo and this app can never drift
from its siblings again.

On the device rangerkit is vendored beside core/ (the install stage puts
it there); in the repo it lives one level up, in apps/ — the fallback
import covers whichever caller forgot to arrange sys.path first.
"""
import sys
from pathlib import Path

try:
    from rangerkit import chords as _shared
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from rangerkit import chords as _shared

sys.modules[__name__] = _shared
