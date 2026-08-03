"""The project file — everything the player made, one JSON document.

``.mrproj`` holds the parameter tree (the same shape scenes capture), the
scene slots, the route list and the seed. Deployment state (ports, panel,
button map) stays in config.toml; a project moved between units must sound
the same, not re-plug their cables.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

EXTENSION = ".mrproj"
FORMAT = 1
DEFAULT_SEED = 0xC0FFEE


@dataclass(frozen=True, slots=True)
class Project:
    name: str = "untitled"
    bpm: float = 120.0
    seed: int = DEFAULT_SEED
    params: dict = field(default_factory=dict)      # the scene-shaped tree
    scenes: dict = field(default_factory=dict)      # slot -> scene dict

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"format": FORMAT, "name": self.name, "bpm": self.bpm,
                    "seed": self.seed, "params": self.params,
                    "scenes": {str(k): v for k, v in self.scenes.items()}}
        path.write_text(json.dumps(document, indent=1, sort_keys=True),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if int(data.get("format", 0)) > FORMAT:
            raise ValueError(f"project format {data.get('format')} is newer "
                             f"than this build understands")
        return cls(name=str(data.get("name", "untitled")),
                   bpm=float(data.get("bpm", 120.0)),
                   seed=int(data.get("seed", DEFAULT_SEED)),
                   params=dict(data.get("params") or {}),
                   scenes={int(k): v
                           for k, v in (data.get("scenes") or {}).items()
                           if str(k).lstrip("-").isdigit()})

    def renamed(self, name: str) -> "Project":
        return replace(self, name=name.strip() or "untitled")


def default_project() -> Project:
    """A useful zero state: DIN and USB thru to DIN out, rack disengaged."""
    return Project(params={
        "routes": [
            {"src": "din_in", "dst": "din_out", "channel": -1,
             "to_channel": -1},
            {"src": "usb_in", "dst": "din_out", "channel": -1,
             "to_channel": -1},
        ],
    })
