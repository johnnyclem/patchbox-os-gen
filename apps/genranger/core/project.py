"""The project file — the rules of the piece, one JSON document.

``.gvproj`` holds the layer parameter trees, seeds, macros, cruise settings
and the seed slots. Deployment state (ports, panel, button map) stays in
config.toml; a project moved between units must evolve identically — that
is the determinism contract in file form.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

EXTENSION = ".gvproj"
FORMAT = 1
DEFAULT_SEED = 0x5EED


@dataclass(frozen=True, slots=True)
class Project:
    name: str = "untitled"
    bpm: float = 100.0
    seed: int = DEFAULT_SEED
    params: dict = field(default_factory=dict)      # the captured state tree
    seeds: dict = field(default_factory=dict)       # slot -> state dict

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"format": FORMAT, "name": self.name, "bpm": self.bpm,
                    "seed": self.seed, "params": self.params,
                    "seeds": {str(k): v for k, v in self.seeds.items()}}
        path.write_text(json.dumps(document, indent=1, sort_keys=True),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if int(data.get("format", 0)) > FORMAT:
            raise ValueError(f"project format {data.get('format')} is newer "
                             f"than this build understands")
        return cls(name=str(data.get("name", "untitled")),
                   bpm=float(data.get("bpm", 100.0)),
                   seed=int(data.get("seed", DEFAULT_SEED)),
                   params=dict(data.get("params") or {}),
                   seeds={int(k): v
                          for k, v in (data.get("seeds") or {}).items()
                          if str(k).lstrip("-").isdigit()})

    def renamed(self, name: str) -> "Project":
        return replace(self, name=name.strip() or "untitled")


def default_project() -> Project:
    """The factory piece: four layers that sound the moment play is pressed
    — the "<3 minutes from blank" metric starts from *not blank*.

    C minor at 100 BPM: a Euclidean kick lattice on the drum channel, a
    Markov walking bass, a sparse probability-grid melody, and long random
    harmony pads. Cruise on, gentle.
    """
    return Project(params={
        "layers": [
            {"role": "rhythm", "algorithm": "euclid", "dest": "din_out",
             "channel": 9, "octave_low": 2, "octave_high": 2, "pulses": 4,
             "density": 0.6, "velocity": 110, "scale": "minor"},
            {"role": "bass", "algorithm": "markov", "dest": "din_out",
             "channel": 0, "octave_low": 2, "octave_high": 3,
             "style": "walk", "density": 0.55, "note_length": "legato",
             "scale": "minor"},
            {"role": "melody", "algorithm": "grid", "dest": "din_out",
             "channel": 1, "octave_low": 4, "octave_high": 5,
             "density": 0.4, "scale": "minor"},
            {"role": "harmony", "algorithm": "random", "dest": "din_out",
             "channel": 2, "octave_low": 3, "octave_high": 4,
             "density": 0.2, "note_length": "drone", "max_interval": 3,
             "velocity": 70, "scale": "minor"},
        ],
        "key": {"root": 0, "scale": "minor"},
        "cruise": {"on": True, "speed": 0.5, "chaos": 0.35},
        "macros": {"density": 0.5, "complexity": 0.5},
    })
