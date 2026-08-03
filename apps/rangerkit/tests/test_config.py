"""The shared config loader: defaults, forgiveness, and the extra hatch."""
from __future__ import annotations

from pathlib import Path

import pytest

from rangerkit.configbase import RangerConfig, load_config


def test_missing_file_is_pure_defaults():
    config = load_config(None)
    assert config == RangerConfig()
    assert config.display.width == 1280 and config.display.height == 400
    assert config.pots.source == "midi_cc"
    assert config.audio.sample_rate == 48000


def test_load_and_unknown_keys_dropped(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text("""
[display]
width = 800
height = 480
hologram = true

[midi]
backend = "null"
prefer = ["pimidi", "pisound"]

[pots]
source = "socket"
cc_a = 74
map = { pot_a = "master_filter" }

[button.map]
click_1 = "play_stop"

[routing]
routes = [{ src = "din_in", dst = "usb_out" }]

[grooveranger]
kits_dir = "/var/lib/grooveranger/kits"
""", encoding="utf-8")
    config = load_config(toml)
    assert (config.display.width, config.display.height) == (800, 480)
    assert config.midi.backend == "null"
    assert config.midi.prefer == ("pimidi", "pisound")
    assert config.pots.source == "socket" and config.pots.cc_a == 74
    assert config.pots.map == {"POT_A": "master_filter"}
    assert config.button.map == {"CLICK_1": "play_stop"}
    assert config.routing.routes == ({"src": "din_in", "dst": "usb_out"},)
    # App tables the kit does not know land in extra, verbatim.
    assert config.extra["grooveranger"]["kits_dir"] \
        == "/var/lib/grooveranger/kits"


def test_malformed_file_raises(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text("[display\nwidth = ", encoding="utf-8")
    with pytest.raises(Exception):
        load_config(toml)


def test_paths_derive_from_data_dir(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[paths]\ndata_dir = "/var/lib/testranger"\n',
                    encoding="utf-8")
    config = load_config(toml)
    assert config.paths.presets_dir == Path("/var/lib/testranger/presets")
    assert config.paths.projects_dir == Path("/var/lib/testranger/projects")
