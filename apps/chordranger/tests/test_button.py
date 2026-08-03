"""The PiSound button bridge: the map, the protocol, and the socket."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.button import (ACTIONS, ButtonServer, DEFAULT_MAP, normalise_map,
                         send, socket_path)
from core.clock import FakeClock
from core.config import AppConfig, ButtonConfig, PathsConfig
from core.engine import Engine
from core.midi_io import CaptureMidiIO
from core.project import default_project


@pytest.fixture()
def server(tmp_path):
    config = AppConfig(paths=PathsConfig(data_dir=tmp_path),
                       button=ButtonConfig(socket=str(tmp_path / "b.sock")))
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    button = ButtonServer(engine, config)
    yield button, engine
    button.stop()


# --- the map ------------------------------------------------------------------

def test_the_default_map_covers_the_gestures_the_hardware_sends():
    for gesture in ("CLICK_1", "CLICK_2", "HOLD_1S", "HOLD_5S"):
        assert gesture in DEFAULT_MAP
    assert set(DEFAULT_MAP.values()) <= set(ACTIONS)


def test_config_entries_override_the_defaults():
    merged = normalise_map({"CLICK_1": "panic"})
    assert merged["CLICK_1"] == "panic"
    assert merged["CLICK_2"] == DEFAULT_MAP["CLICK_2"]


def test_gesture_names_are_case_insensitive():
    assert normalise_map({"click_1": "metronome"})["CLICK_1"] == "metronome"


def test_an_unknown_action_is_dropped_not_fatal():
    merged = normalise_map({"CLICK_1": "make coffee"})
    assert merged["CLICK_1"] == DEFAULT_MAP["CLICK_1"]


def test_the_socket_path_defaults_under_the_data_dir(tmp_path):
    config = AppConfig(paths=PathsConfig(data_dir=tmp_path))
    assert socket_path(config) == tmp_path / "button.sock"


def test_an_explicit_socket_path_wins(tmp_path):
    config = AppConfig(paths=PathsConfig(data_dir=tmp_path),
                       button=ButtonConfig(socket="/run/chordranger/b.sock"))
    assert socket_path(config) == Path("/run/chordranger/b.sock")


# --- the protocol -------------------------------------------------------------

def test_ping_answers_pong(server):
    button, _engine = server
    assert button.handle("PING") == "PONG"


def test_map_and_actions_are_introspectable(server):
    button, _engine = server
    assert "CLICK_1=play_stop" in button.handle("MAP")
    assert "panic" in button.handle("ACTIONS")


def test_an_empty_or_unmapped_request_is_an_error_not_a_crash(server):
    button, _engine = server
    assert button.handle("") .startswith("ERR")
    assert button.handle("CLICK_9").startswith("ERR unmapped")


def test_one_click_toggles_the_transport(server):
    button, engine = server
    assert button.handle("CLICK_1") == "OK play_stop"
    engine.step()
    assert engine.playing
    button.handle("CLICK_1")
    engine.step()
    assert not engine.playing


def test_two_clicks_arm_recording(server):
    button, engine = server
    button.handle("CLICK_2")
    engine.step()
    assert engine.recording


def test_a_long_hold_panics(server):
    button, engine = server
    button.handle("CLICK_1")
    for _ in range(400):
        engine.step()
    button.handle("HOLD_5S")
    engine.step()
    assert not engine.playing


def test_three_clicks_walk_the_sections_the_style_actually_has(server):
    button, engine = server
    before = engine.arranger.section
    button.handle("CLICK_3")
    engine.step()
    assert engine.arranger.section != before or engine.playing


def test_holding_three_seconds_changes_style(server):
    button, engine = server
    before = engine.style.name
    button.handle("HOLD_3S")
    engine.step()
    assert engine.style.name != before


def test_a_message_hook_is_called_for_panel_feedback(server):
    button, engine = server
    seen: list[str] = []
    button.on_message = seen.append
    button.handle("CLICK_1")
    assert seen and "PLAY" in seen[0]


# --- the socket ---------------------------------------------------------------

def test_the_server_binds_and_answers_over_a_real_socket(server):
    button, _engine = server
    assert button.start()
    assert send(button.path, "PING") == "PONG"


def test_stopping_removes_the_socket_node(server):
    button, _engine = server
    assert button.start()
    path = button.path
    button.stop()
    assert not path.exists()


def test_an_unbindable_socket_is_reported_rather_than_raised(tmp_path):
    config = AppConfig(
        paths=PathsConfig(data_dir=tmp_path),
        button=ButtonConfig(socket="/proc/definitely/not/here.sock"))
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    assert ButtonServer(engine, config).start() is False


def test_save_writes_the_project_when_nothing_else_is_listening(tmp_path):
    config = AppConfig(paths=PathsConfig(data_dir=tmp_path),
                       button=ButtonConfig(socket=str(tmp_path / "b.sock")))
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    button = ButtonServer(engine, config)
    assert button.handle("HOLD_1S") == "OK save_project"
    assert list(config.paths.projects_dir.glob("*.crproj"))


def test_save_prefers_the_host_hook_when_the_gui_is_up(server):
    button, _engine = server
    called: list[bool] = []
    button.on_save = lambda: called.append(True)
    button.handle("HOLD_1S")
    assert called
