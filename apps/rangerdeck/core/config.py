"""Appliance configuration — ``/etc/rangerdeck/config.toml``.

The deck reads the family-shared schema (display, paths — it has no MIDI,
no engine and no pots of its own) plus tables of its own in
``RangerConfig.extra``:

    [deck]
    # Where the per-app handover sockets live. The appliance points this at
    # /run/rangerdeck (created by the unit's RuntimeDirectory=); empty means
    # a fresh temp dir, which is what a dev box wants.
    run_dir = "/run/rangerdeck"
    # Tile order. Apps missing from the machine are simply not shown, so
    # this list can name the whole suite on every build.
    apps = ["chordranger", "midiranger", "genranger", "phraseranger",
            "sceneranger", "grooveranger", "synthranger"]

    [updates]
    # On launch, fetch apps/rangers-channel.json from the git branch you
    # push to and offer Install when the tip moved. See core/updates.py.
    enabled = true
    check_on_launch = true
    channel_url = "https://raw.githubusercontent.com/…/rangers-channel.json"
    git_url = "https://github.com/johnnyclem/patchbox-os-gen.git"
    git_ref = "patchbox-2024-01"
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rangerkit.configbase import RangerConfig, load_config

from core.updates import UpdateSettings, update_settings

__all__ = ["RangerConfig", "load_config", "DeckSettings", "deck_settings",
           "UpdateSettings", "update_settings"]


@dataclass(frozen=True, slots=True)
class DeckSettings:
    run_dir: Path | None
    apps: tuple[str, ...]


def deck_settings(config: RangerConfig) -> DeckSettings:
    raw = config.extra.get("deck", {}) if hasattr(config, "extra") else {}
    run_dir = str(raw.get("run_dir", "") or "").strip()
    apps = tuple(str(name).strip().lower()
                 for name in raw.get("apps", ()) if str(name).strip())
    return DeckSettings(run_dir=Path(run_dir) if run_dir else None,
                        apps=apps)
