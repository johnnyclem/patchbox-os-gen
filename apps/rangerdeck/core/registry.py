"""Which Ranger apps this machine actually has, and how to start each one.

One rule covers both worlds: an app lives in the directory *next to* the
deck's own — ``/opt/<app>`` beside ``/opt/rangerdeck`` on the appliance,
``apps/<app>`` beside ``apps/rangerdeck`` in the repo. If the sibling has a
``venv`` we use its interpreter (the appliance), otherwise the deck's own
(the dev box); if ``/etc/<app>/config.toml`` exists it is passed through.
An app that is not on disk simply grows no tile — the deck never advertises
something it cannot start.

RK-00pi is deliberately absent: it is a git submodule that does not speak
the deck protocol (yet), and it remains reachable the systemd way with
``patchbox-app enable rk00pi``.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Suite order, matching RANGER-SUITE-PLAN.md. The tagline is the tile's
# second line — lower case, the way the panels caption everything.
KNOWN_APPS: tuple[tuple[str, str, str], ...] = (
    ("chordranger", "ChordRanger", "chord pads + backing band"),
    ("midiranger", "MidiRanger", "midi matrix · arps · note fx"),
    ("genranger", "GenRanger", "generative sequencer"),
    ("phraseranger", "PhraseRanger", "phrase looper + slicer"),
    ("sceneranger", "SceneRanger", "clip + scene launcher"),
    ("grooveranger", "GrooveRanger", "sample groovebox"),
    ("synthranger", "SynthRanger", "multi-engine poly synth"),
)


@dataclass(frozen=True, slots=True)
class AppSpec:
    """Everything the fleet needs to run one guest app.

    ``command`` is the full argv *without* the deck socket — the fleet
    appends ``--deck-socket <path>`` when it spawns, so the spec stays a
    plain description and the socket stays the fleet's business.
    """

    name: str
    title: str
    tagline: str
    command: tuple[str, ...]


def _spec_for(name: str, title: str, tagline: str, root: Path,
              fullscreen: bool, size: tuple[int, int]) -> AppSpec | None:
    main = root / name / "main.py"
    if not main.is_file():
        return None
    venv_python = root / name / "venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    command = [python, str(main)]
    etc = Path("/etc") / name / "config.toml"
    if etc.is_file():
        command += ["--config", str(etc)]
    if fullscreen:
        command.append("--fullscreen")
    else:
        # A dev window should come up the same size as the deck's, or the
        # handover visibly jumps between two window shapes.
        command += ["--size", f"{size[0]}x{size[1]}"]
    return AppSpec(name, title, tagline, tuple(command))


def discover(order: tuple[str, ...] = (), root: Path | None = None,
             fullscreen: bool = False,
             size: tuple[int, int] = (1280, 400)) -> tuple[AppSpec, ...]:
    """The installed suite, in config order (or the suite's own).

    ``order`` names from ``[deck] apps`` filter *and* sort; unknown names
    are dropped with no fuss so a config written for a later firmware still
    boots this one.
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent
    known = {name: (title, tagline) for name, title, tagline in KNOWN_APPS}
    names = [n for n in order if n in known] if order \
        else [name for name, _, _ in KNOWN_APPS]
    specs = []
    for name in names:
        title, tagline = known[name]
        spec = _spec_for(name, title, tagline, root, fullscreen, size)
        if spec is not None:
            specs.append(spec)
    return tuple(specs)
