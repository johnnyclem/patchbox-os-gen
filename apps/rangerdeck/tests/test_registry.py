"""Discovery: tiles only for apps that are actually on disk."""
from __future__ import annotations

import sys

from core.registry import KNOWN_APPS, discover


def _fake_suite(tmp_path, names):
    for name in names:
        app_dir = tmp_path / name
        app_dir.mkdir()
        (app_dir / "main.py").write_text("# stub\n")
    return tmp_path


def test_discover_skips_apps_that_are_not_installed(tmp_path):
    root = _fake_suite(tmp_path, ["midiranger", "genranger"])
    specs = discover(root=root)
    assert [s.name for s in specs] == ["midiranger", "genranger"]


def test_discover_keeps_suite_order_by_default(tmp_path):
    everyone = [name for name, _, _ in KNOWN_APPS]
    root = _fake_suite(tmp_path, list(reversed(everyone)))
    specs = discover(root=root)
    assert [s.name for s in specs] == everyone


def test_config_order_filters_and_sorts(tmp_path):
    root = _fake_suite(tmp_path, ["midiranger", "genranger", "synthranger"])
    specs = discover(order=("synthranger", "midiranger", "nosuchranger"),
                     root=root)
    assert [s.name for s in specs] == ["synthranger", "midiranger"]


def test_dev_spec_uses_our_interpreter_and_window_size(tmp_path):
    root = _fake_suite(tmp_path, ["midiranger"])
    (spec,) = discover(root=root, fullscreen=False, size=(800, 480))
    assert spec.command[0] == sys.executable
    assert spec.command[1].endswith("midiranger/main.py")
    assert "--size" in spec.command
    assert "800x480" in spec.command
    assert "--fullscreen" not in spec.command


def test_appliance_spec_prefers_the_apps_own_venv(tmp_path):
    root = _fake_suite(tmp_path, ["midiranger"])
    venv_python = root / "midiranger" / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("")
    (spec,) = discover(root=root, fullscreen=True)
    assert spec.command[0] == str(venv_python)
    assert "--fullscreen" in spec.command
    assert "--size" not in spec.command


def test_specs_never_carry_the_socket_themselves(tmp_path):
    root = _fake_suite(tmp_path, ["midiranger"])
    (spec,) = discover(root=root)
    assert "--deck-socket" not in spec.command
