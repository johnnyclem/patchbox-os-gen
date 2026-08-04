"""The project file — the whole rig, one JSON document.

``.syproj`` holds the four parts (both patches, morph, matrix, mix).
Deployment state (ports, panel, button map) stays in config.toml.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

EXTENSION = ".syproj"
FORMAT = 1
DEFAULT_SEED = 0x51E9


@dataclass(frozen=True, slots=True)
class Project:
    name: str = "untitled"
    bpm: float = 120.0
    seed: int = DEFAULT_SEED
    params: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"format": FORMAT, "name": self.name, "bpm": self.bpm,
                    "seed": self.seed, "params": self.params}
        path.write_text(json.dumps(document, indent=1, sort_keys=True),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if int(data.get("format", 0)) > FORMAT:
            raise ValueError(f"project format {data.get('format')} is "
                             f"newer than this build understands")
        return cls(name=str(data.get("name", "untitled")),
                   bpm=float(data.get("bpm", 120.0)),
                   seed=int(data.get("seed", DEFAULT_SEED)),
                   params=dict(data.get("params") or {}))

    def renamed(self, name: str) -> "Project":
        return replace(self, name=name.strip() or "untitled")


def default_project() -> Project:
    """Four INIT parts on channels 1–4 — the engine builds them itself
    when params carry no parts."""
    return Project()
