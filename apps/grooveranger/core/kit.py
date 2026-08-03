"""Kits — twelve pads, a home directory, and one destination.

A kit is loaded from ``<dir>/kit.json`` whose ``pads`` name WAV files in the
same directory. Built-in kits ship under the app's ``data/kits`` and user
kits live in ``[paths] data_dir``/kits — ``list_kits`` scans both, built-ins
first. The kit also owns the routing: ``dest`` says where pad hits go
(``internal`` = the sampler on the DAC) and ``channel`` is the emitted
channel *for external destinations only* — internally each pad speaks on its
own channel (the pad index), which is what makes per-pad CCs possible. See
``docs/ARCHITECTURE.md`` for that contract.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.pad import PadDef
from core.steps import PADS

log = logging.getLogger("grooveranger.kit")

KIT_FILE = "kit.json"
DEFAULT_KIT = "rk909"
#: name, GM-ish note, choke group, mute group
_FALLBACK_PADS = (
    ("KICK", 36, 0, 0), ("SNAR", 38, 0, 0), ("CLAP", 39, 0, 0),
    ("RIM", 37, 0, 0), ("CHAT", 42, 1, 1), ("OHAT", 46, 1, 1),
    ("LTOM", 45, 0, 0), ("HTOM", 50, 0, 0), ("RIDE", 51, 0, 2),
    ("CRSH", 49, 0, 2), ("COWB", 56, 0, 0), ("SHKR", 70, 0, 0),
)


def _fallback_pads() -> tuple:
    return tuple(PadDef(name=name, note=note, choke=choke, group=group)
                 for name, note, choke, group in _FALLBACK_PADS)


@dataclass(frozen=True, slots=True)
class Kit:
    name: str = DEFAULT_KIT
    directory: str = ""          # where the layer WAVs live ("" = no samples)
    pads: tuple = field(default_factory=_fallback_pads)
    dest: str = "internal"
    channel: int = 9             # external channel (MIDI channel 10, drums)

    def normalised(self) -> "Kit":
        pads = tuple(pad.normalised() for pad in self.pads[:PADS])
        pads += tuple(PadDef() for _ in range(PADS - len(pads)))
        return replace(self, pads=pads,
                       channel=max(0, min(15, int(self.channel))))

    def pad_for_note(self, note: int) -> int:
        for index, pad in enumerate(self.pads):
            if pad.note == note:
                return index
        return -1

    def with_pad(self, index: int, pad: PadDef) -> "Kit":
        pads = list(self.pads)
        pads[index] = pad.normalised()
        return replace(self, pads=tuple(pads))

    def to_config(self) -> dict:
        return {"name": self.name, "directory": self.directory,
                "dest": self.dest, "channel": self.channel,
                "pads": [pad.to_config() for pad in self.pads]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Kit":
        raw = raw or {}
        pads = tuple(PadDef.from_config(entry)
                     for entry in raw.get("pads", []))
        return cls(name=str(raw.get("name", DEFAULT_KIT)),
                   directory=str(raw.get("directory", "")),
                   pads=pads or _fallback_pads(),
                   dest=str(raw.get("dest", "internal")),
                   channel=int(raw.get("channel", 9))).normalised()


def load_kit(directory: Path) -> Kit:
    """Read ``kit.json`` from a kit directory. Raises OSError/ValueError on
    a broken kit — callers decide whether that is fatal (boot) or a panel
    message (browsing)."""
    raw = json.loads((directory / KIT_FILE).read_text(encoding="utf-8"))
    kit = Kit.from_config(raw)
    return replace(kit, name=raw.get("name", directory.name),
                   directory=str(directory)).normalised()


def kit_roots(config) -> list[Path]:
    """Built-in kits first, then the user's."""
    roots = [Path(__file__).resolve().parent.parent / "data" / "kits"]
    data_dir = getattr(getattr(config, "paths", None), "data_dir", None)
    if data_dir:
        roots.append(Path(data_dir) / "kits")
    return roots


def list_kits(config) -> list[Path]:
    found: dict[str, Path] = {}
    for root in kit_roots(config):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if (entry / KIT_FILE).is_file() and entry.name not in found:
                found[entry.name] = entry
    return list(found.values())


def default_kit(config=None) -> Kit:
    """The shipped kit, or the sample-less fallback when data/ is missing —
    a broken install still boots, emits MIDI, and says so on the panel."""
    for root in kit_roots(config):
        candidate = root / DEFAULT_KIT
        if (candidate / KIT_FILE).is_file():
            try:
                return load_kit(candidate)
            except (OSError, ValueError) as exc:
                log.warning("default kit unreadable (%s)", exc)
    log.warning("no kit data found — pads will emit MIDI only")
    return Kit().normalised()
