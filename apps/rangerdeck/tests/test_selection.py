"""Tile selection: override file, resolve order, save."""
from __future__ import annotations

from pathlib import Path

from core.selection import KNOWN_NAMES, load_enabled, resolve_order, save_enabled


def test_load_enabled_missing_returns_none(tmp_path):
    assert load_enabled(tmp_path / "nope.txt") is None


def test_load_enabled_parses_lines_and_commas(tmp_path):
    path = tmp_path / "enabled-apps.txt"
    path.write_text("# comment\nmidiranger\ngenranger, synthranger\nnosuch\n")
    assert load_enabled(path) == ("midiranger", "genranger", "synthranger")


def test_resolve_order_prefers_override(tmp_path):
    path = tmp_path / "enabled-apps.txt"
    path.write_text("synthranger\nmidiranger\n")
    assert resolve_order(("chordranger", "midiranger"), path=path) == (
        "synthranger", "midiranger")


def test_resolve_order_falls_back_to_config(tmp_path):
    assert resolve_order(("midiranger", "genranger"),
                         path=tmp_path / "missing") == (
        "midiranger", "genranger")


def test_resolve_order_falls_back_to_suite(tmp_path):
    assert resolve_order((), path=tmp_path / "missing") == KNOWN_NAMES


def test_save_enabled_writes_file_and_config(tmp_path):
    path = tmp_path / "enabled-apps.txt"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[deck]\nrun_dir = "/run/x"\n'
        'apps = ["chordranger", "midiranger"]\n'
    )
    saved = save_enabled(["genranger", "midiranger", "bogus"],
                         path=path, config_toml=cfg)
    assert saved == ("genranger", "midiranger")
    assert "genranger" in path.read_text()
    text = cfg.read_text()
    assert "genranger" in text and "midiranger" in text
    assert "chordranger" not in text
