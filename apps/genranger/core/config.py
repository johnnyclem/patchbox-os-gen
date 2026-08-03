"""Appliance configuration — ``/etc/genranger/config.toml``.

GenRanger has no config sections of its own: everything it needs (display,
paths, midi, clock, engine, button, pots) is the family-shared schema in
``rangerkit.configbase``. This module exists so the app spells
``core.config.load_config`` like its siblings do, and so a future
app-specific table has one obvious home.
"""
from __future__ import annotations

from rangerkit.configbase import RangerConfig, load_config

__all__ = ["RangerConfig", "load_config"]
