"""Appliance configuration — ``/etc/synthranger/config.toml``.

SynthRanger uses the family-shared schema in ``rangerkit.configbase``.
Patches are data, not configuration: factory presets ship under the app's
``data/presets`` and user presets under ``[paths] presets_dir``.
"""
from __future__ import annotations

from rangerkit.configbase import RangerConfig, load_config

__all__ = ["RangerConfig", "load_config"]
