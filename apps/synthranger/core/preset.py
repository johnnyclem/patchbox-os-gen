"""Presets — one patch per JSON file, factory bank + user directory.

Factory presets ship read-only in the app's ``data/presets``; user saves
land in ``[paths] presets_dir``. Listing is factory first, then user,
names deduplicated user-wins so a player can shadow a factory sound.
File I/O stays on the App's thread — the engine only ever sees a parsed
patch dict.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.patch import Patch

log = logging.getLogger("synthranger.preset")

EXTENSION = ".synpatch"


def factory_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "presets"


def user_dir(config) -> Path | None:
    presets = getattr(getattr(config, "paths", None), "presets_dir", None)
    return Path(presets) if presets else None


def list_presets(config) -> list[Path]:
    found: dict[str, Path] = {}
    for root in (factory_dir(), user_dir(config)):
        if root is None or not root.is_dir():
            continue
        for entry in sorted(root.glob(f"*{EXTENSION}")):
            found[entry.stem] = entry
    return sorted(found.values(), key=lambda p: p.stem.lower())


def load_preset(path: Path) -> Patch:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    patch = Patch.from_config(raw)
    if "name" not in raw:
        from dataclasses import replace
        patch = replace(patch, name=path.stem).normalised()
    return patch


def save_preset(directory: Path, patch: Patch) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{patch.name.lower().replace(' ', '-')}" \
        f"{EXTENSION}"
    path.write_text(json.dumps(patch.to_config(), indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")
    return path
