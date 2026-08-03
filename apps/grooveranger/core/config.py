"""Appliance configuration — ``/etc/grooveranger/config.toml``.

GrooveRanger uses the family-shared schema in ``rangerkit.configbase``
(display, paths, midi, routing, clock, engine, button, pots, audio). Kits are
data, not configuration: the built-ins ship under the app's ``data/kits`` and
user kits live under ``[paths] data_dir``.
"""
from __future__ import annotations

from rangerkit.configbase import RangerConfig, load_config

__all__ = ["RangerConfig", "load_config"]
