"""The project file — every take, one JSON document.

``.prproj`` holds the eight tracks (params + phrases), the scene slots and
the global loop length. Deployment state (ports, panel, button map) stays
in config.toml; a project moved between units must play the same takes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

EXTENSION = ".prproj"
FORMAT = 1
DEFAULT_SEED = 0x100B


@dataclass(frozen=True, slots=True)
class Project:
    name: str = "untitled"
    bpm: float = 120.0
    seed: int = DEFAULT_SEED
    params: dict = field(default_factory=dict)      # the captured state tree
    scenes: dict = field(default_factory=dict)      # slot -> state dict

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
    """Eight empty one-bar tracks: DIN out, channels 0–7, track 1 armed by
    the engine at boot so play-and-it-records is the very first gesture."""
    return Project(params={
        "tracks": [{"params": {"dest": "din_out", "channel": channel}}
                   for channel in range(8)],
        "global_bars": 1,
    })
