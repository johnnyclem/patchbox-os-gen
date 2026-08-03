"""The project file — the whole groove, one JSON document.

``.grproj`` holds the eight patterns, the kit (serialized in full, so a
project moved between units sounds the same even where the kit files
differ), the mixer, the song chain and swing. Deployment state (ports,
panel, button map) stays in config.toml.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

EXTENSION = ".grproj"
FORMAT = 1
DEFAULT_SEED = 0x6600E


@dataclass(frozen=True, slots=True)
class Project:
    name: str = "untitled"
    bpm: float = 120.0
    seed: int = DEFAULT_SEED
    params: dict = field(default_factory=dict)      # the captured state tree

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
            raise ValueError(f"project format {data.get('format')} is newer "
                             f"than this build understands")
        return cls(name=str(data.get("name", "untitled")),
                   bpm=float(data.get("bpm", 120.0)),
                   seed=int(data.get("seed", DEFAULT_SEED)),
                   params=dict(data.get("params") or {}))

    def renamed(self, name: str) -> "Project":
        return replace(self, name=name.strip() or "untitled")


def default_project() -> Project:
    """Pattern 1 carries a four-on-the-floor starter — a groovebox that
    boots into silence makes the demo counter person invent one anyway."""
    from core.steps import Pattern
    pattern = Pattern()
    for step in range(0, 16, 4):
        pattern = pattern.toggle(0, step)               # kick on quarters
    for step in (4, 12):
        pattern = pattern.toggle(1, step)               # snare backbeat
    for step in range(0, 16, 2):
        pattern = pattern.toggle(4, step)               # 8th closed hats
    pattern = pattern.toggle(5, 14)                     # open hat pickup
    return Project(params={"sequencer": {
        "patterns": [pattern.to_config()], "current": 0, "swing": 0.54}})
