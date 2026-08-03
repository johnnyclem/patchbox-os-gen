"""The button bridge protocol, driven without a socket."""
from __future__ import annotations

from pathlib import Path

from rangerkit.button import (ButtonServer, DEFAULT_MAP, _gesture_from_words,
                              normalise_map)


def server(calls):
    actions = {name: (lambda name=name: calls.append(name))
               for name in ("play_stop", "record_toggle", "save_project",
                            "panic")}
    return ButtonServer(actions, Path("/tmp/unused.sock"))


def test_ping_map_actions():
    calls = []
    bridge = server(calls)
    assert bridge.handle("PING") == "PONG"
    assert "CLICK_1=play_stop" in bridge.handle("MAP")
    assert "panic" in bridge.handle("ACTIONS")
    assert "nothing" in bridge.handle("ACTIONS")
    assert not calls


def test_gestures_run_mapped_actions():
    calls = []
    bridge = server(calls)
    assert bridge.handle("CLICK_1") == "OK play_stop"
    assert bridge.handle("HOLD_5S") == "OK panic"
    assert calls == ["play_stop", "panic"]


def test_pisound_word_shapes_are_accepted():
    calls = []
    bridge = server(calls)
    assert bridge.handle("CLICK 2") == "OK record_toggle"
    # A 4-second hold rounds *down* past the 3 s threshold; unmapped here.
    assert bridge.handle("HOLD 1 4").startswith("ERR unmapped HOLD_3S")
    assert bridge.handle("HOLD 1 6") == "OK panic"
    assert calls == ["record_toggle", "panic"]


def test_action_by_name_bypasses_the_map():
    calls = []
    bridge = server(calls)
    assert bridge.handle("ACTION save_project") == "OK save_project"
    assert bridge.handle("ACTION warp") == "ERR unknown action warp"
    assert calls == ["save_project"]


def test_unknown_and_empty_lines():
    bridge = server([])
    assert bridge.handle("").startswith("ERR")
    assert bridge.handle("CLICK_3").startswith("ERR unmapped")
    assert bridge.handle("nothing") .startswith("ERR unmapped")


def test_normalise_map_drops_unknown_actions_keeps_defaults():
    merged = normalise_map({"click_3": "warp_drive", "HOLD_3S": "panic"},
                           ("play_stop", "record_toggle", "save_project",
                            "panic", "nothing"))
    assert merged["HOLD_3S"] == "panic"
    assert "CLICK_3" not in merged
    for gesture, action in DEFAULT_MAP.items():
        assert merged[gesture] == action


def test_hold_rounding():
    assert _gesture_from_words(["HOLD", "1", "1"]) == "HOLD_1S"
    assert _gesture_from_words(["HOLD", "1", "4"]) == "HOLD_3S"
    assert _gesture_from_words(["HOLD", "1", "9"]) == "HOLD_5S"
    assert _gesture_from_words(["HOLD", "1", "0"]) == "HOLD_OTHER"
    assert _gesture_from_words(["CLICK", "9"]) == "CLICK_OTHER"


def test_on_message_echoes_to_the_panel():
    calls, seen = [], []
    bridge = server(calls)
    bridge.on_message = seen.append
    bridge.handle("CLICK_1")
    assert seen == ["BUTTON: PLAY STOP"]
