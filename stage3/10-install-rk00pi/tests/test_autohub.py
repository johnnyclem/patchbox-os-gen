"""Tests for patchbox-rk00pi-autohub.

The tool runs once, unattended, on a unit nobody is watching, and it rewrites
a file the user's music lives in. So the parts worth pinning down are: what
it reads out of the ALSA graph, what hub it builds from that, and — most of
all — when it decides to leave the project alone.

The rig in the bug report is the fixture the whole file is built around: a
Pisound HAT, a USB KeyStep, and an image whose baked hub asks for a Pimidi
that is not on this Pi.
"""
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "files" / "patchbox-rk00pi-autohub"


def _load():
    """Import the tool by path — it ships without a .py suffix because it is
    a command on the unit, not a module."""
    spec = importlib.util.spec_from_loader(
        "autohub", importlib.machinery.SourceFileLoader("autohub", str(TOOL)))
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules[cls.__module__].
    sys.modules["autohub"] = module
    spec.loader.exec_module(module)
    return module


autohub = _load()


# The graph from the unit in the bug report, as /proc/asound/seq/clients
# prints it: Pisound DIN, its control port, a USB KeyStep, Midi Through.
PROC_PISOUND_KEYSTEP = """\
Client   0 : "System" [Kernel]
  Port   0 : "Timer" (Rwe-)
  Port   1 : "Announce" (R-e-)
Client  14 : "Midi Through" [Kernel]
  Port   0 : "Midi Through Port-0" (RWeX)
Client  20 : "pisound" [Kernel Card=1]
  Port   0 : "pisound MIDI PS-1YJZ1HQ" (RWeX)
Client  24 : "pisound-ctl" [User Legacy]
  Port   0 : "pisound-ctl" (RWeX)
Client  28 : "Arturia KeyStep 37" [Kernel Card=2]
  Port   0 : "Arturia KeyStep 37 MIDI 1" (RWeX)
"""

PROC_PIMIDI = """\
Client   0 : "System" [Kernel]
  Port   0 : "Timer" (Rwe-)
Client  20 : "pimidi0" [Kernel Card=1]
  Port   0 : "pimidi-a" (RWeX)
  Port   1 : "pimidi-b" (RWeX)
"""

ACONNECT_IN = """\
client 0: 'System' [type=kernel]
    0 'Timer           '
    1 'Announce        '
client 20: 'pisound' [type=kernel,card=1]
    0 'pisound MIDI PS-1YJZ1HQ'
	Connecting To: 128:0
"""

# The hub the image bakes today — every endpoint on a board this rig lacks.
PIMIDI_HUB = {
    "profile": "custom",
    "endpoints": [
        {"id": "din_in_a", "kind": "din_in", "client_name": "pimidi",
         "port_name": "pimidi-a"},
        {"id": "din_in_b", "kind": "din_in", "client_name": "pimidi",
         "port_name": "pimidi-b"},
        {"id": "din_out_a", "kind": "din_out", "client_name": "pimidi",
         "port_name": "pimidi-a"},
        {"id": "din_out_b", "kind": "din_out", "client_name": "pimidi",
         "port_name": "pimidi-b"},
        {"id": "seq", "kind": "seq"},
        {"id": "rec", "kind": "rec"},
    ],
    "buses": [{"id": 0, "name": "OUT A", "dest_endpoint": "din_out_a",
               "clock_policy": "thru"}],
    "routes": [{"source_endpoint": "din_in_a", "bus_id": 0}],
}


def endpoints(hub):
    return {e["id"]: e for e in hub["endpoints"]}


def buses(hub):
    return {b["id"]: b for b in hub["buses"]}


# --- reading the graph --------------------------------------------------------

def test_proc_parse_splits_duplex_ports_into_both_directions():
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    din = [p for p in ports if p.port_name.startswith("pisound MIDI")]
    assert {p.is_input for p in din} == {True, False}


def test_proc_parse_honours_the_capability_field():
    # "Announce" is (R-e-): readable, not writable. One direction only.
    announce = [p for p in autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
                if p.port_name == "Announce"]
    assert [p.is_input for p in announce] == [True]


def test_aconnect_fallback_parses_one_direction():
    ports = autohub.parse_aconnect(ACONNECT_IN, is_input=True)
    assert all(p.is_input for p in ports)
    assert ("pisound", "pisound MIDI PS-1YJZ1HQ") in \
        {(p.client_name, p.port_name) for p in ports}
    # "Connecting To:" is not a port, however indented it looks.
    assert not [p for p in ports if "Connecting" in p.port_name]


@pytest.mark.parametrize("client, family", [
    ("pisound", autohub.PISOUND),
    ("Blokas pisound", autohub.PISOUND),
    ("pisound-ctl", autohub.SOFT),      # the button/control port, not a jack
    ("pimidi0", autohub.PIMIDI),
    ("Arturia KeyStep 37", autohub.USB),
    ("Midi Through", autohub.SOFT),
    ("RK-00pi out", autohub.SOFT),      # our own client, mid-rescan
])
def test_classify(client, family):
    assert autohub.classify(client) == family


# --- building a hub -----------------------------------------------------------

def test_pisound_and_usb_rig_gets_a_din_pair_and_a_usb_pair():
    hub = autohub.build_hub(autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP))
    ids = endpoints(hub)
    assert set(ids) == {"din_in", "din_out", "usb_in", "usb_out", "seq", "rec"}
    # The DIN match must survive a different Pisound (the port name carries a
    # per-board serial) without ever matching the control client.
    assert ids["din_out"]["client_name"] == "pisound"
    assert ids["din_out"]["port_name"] == "pisound MIDI"
    assert ids["usb_in"]["client_name"] == "Arturia KeyStep 37"


def test_generated_hub_binds_every_endpoint_it_declares():
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    resolved, wanted = autohub.fits(autohub.build_hub(ports), ports)
    assert wanted and resolved == wanted


def test_bus_zero_is_the_main_output_and_carries_clock():
    # Track.output_bus defaults to 0, so bus 0 has to be somewhere audible —
    # and the clock policy is what makes a DIN out tick at all.
    hub = autohub.build_hub(autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP))
    assert buses(hub)[0]["dest_endpoint"] == "din_out"
    assert buses(hub)[0]["clock_policy"] == "THRU"
    assert {"source_endpoint": "seq", "bus_id": 0} in hub["routes"]


def test_usb_input_reaches_the_din_out_and_the_recorder():
    hub = autohub.build_hub(autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP))
    rec = next(b["id"] for b in hub["buses"] if b["dest_endpoint"] == "rec")
    targets = {r["bus_id"] for r in hub["routes"]
               if r["source_endpoint"] == "usb_in"}
    assert targets == {0, rec}


def test_usb_only_rig_does_not_echo_the_controller_back_at_itself():
    proc = """\
Client  24 : "Arturia KeyStep 37" [Kernel Card=1]
  Port   0 : "Arturia KeyStep 37 MIDI 1" (RWeX)
"""
    hub = autohub.build_hub(autohub.parse_proc_clients(proc))
    rec = next(b["id"] for b in hub["buses"] if b["dest_endpoint"] == "rec")
    assert {r["bus_id"] for r in hub["routes"]
            if r["source_endpoint"] == "usb_in"} == {rec}


def test_pimidi_rig_keeps_the_two_trs_jacks_apart():
    hub = autohub.build_hub(autohub.parse_proc_clients(PROC_PIMIDI))
    ids = endpoints(hub)
    assert ids["din_out_a"]["port_name"] == "pimidi-a"
    assert ids["din_out_b"]["port_name"] == "pimidi-b"
    # Client match stays loose: the real client is "pimidi0" (board select).
    assert ids["din_out_a"]["client_name"] == "pimidi"
    dests = {b["dest_endpoint"] for b in hub["buses"]}
    assert {"din_out_a", "din_out_b", "rec"} == dests


def test_send_only_device_gets_no_output_endpoint():
    proc = """\
Client  24 : "Tiny Controller" [Kernel Card=1]
  Port   0 : "Tiny Controller MIDI 1" (R-e-)
"""
    hub = autohub.build_hub(autohub.parse_proc_clients(proc))
    assert set(endpoints(hub)) == {"usb_in", "seq", "rec"}


def test_a_rig_with_no_midi_hardware_builds_an_empty_but_valid_hub():
    hub = autohub.build_hub(autohub.parse_proc_clients(
        'Client  14 : "Midi Through" [Kernel]\n'
        '  Port   0 : "Midi Through Port-0" (RWeX)\n'))
    assert set(endpoints(hub)) == {"seq", "rec"}
    assert autohub.fits(hub, []) == (0, 0)


# --- the decision to rewrite --------------------------------------------------

def test_the_reported_bug_is_detected_and_fixed():
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    assert autohub.fits(PIMIDI_HUB, ports) == (0, 4)    # nothing binds
    change, why = autohub.should_apply(PIMIDI_HUB, autohub.build_hub(ports),
                                       ports)
    assert change and "0/4" in why


def test_a_hub_that_already_fits_is_left_alone():
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    hub = autohub.build_hub(ports)
    change, why = autohub.should_apply(hub, hub, ports)
    assert not change and "already fits" in why


def test_a_partly_bound_hub_is_not_replaced_by_a_worse_one():
    # Pimidi rig, but the project only declares the A jack: 2/2 resolve, so
    # the user's deliberately smaller hub survives.
    ports = autohub.parse_proc_clients(PROC_PIMIDI)
    hand_made = {
        "endpoints": [
            {"id": "din_in_a", "kind": "din_in", "client_name": "pimidi",
             "port_name": "pimidi-a"},
            {"id": "din_out_a", "kind": "din_out", "client_name": "pimidi",
             "port_name": "pimidi-a"},
        ],
        "buses": [], "routes": [],
    }
    change, _ = autohub.should_apply(hand_made, autohub.build_hub(ports),
                                     ports)
    assert not change


def test_a_silent_rig_never_loses_the_users_routing():
    # No MIDI hardware at all: the generated hub binds nothing, so replacing
    # a hand-built hub with it would only destroy work.
    change, _ = autohub.should_apply(PIMIDI_HUB, autohub.build_hub([]), [])
    assert not change


# --- writing the project ------------------------------------------------------

def _project(tmp_path, hub):
    path = tmp_path / "starter.rkproj"
    path.write_text(json.dumps({
        "schema_version": 5, "name": "starter", "hub": hub,
        "tracks": [{"index": 0, "output_bus": 0}],
    }), encoding="utf-8")
    return path


def test_apply_rewrites_the_hub_and_keeps_everything_else(tmp_path):
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    path = _project(tmp_path, PIMIDI_HUB)
    assert autohub.apply_to_project(path, autohub.build_hub(ports), ports)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["schema_version"] == 5
    assert after["tracks"] == [{"index": 0, "output_bus": 0}]
    assert "din_out" in endpoints(after["hub"])
    # The project carries its own schema_version; the hub must not add one.
    assert "schema_version" not in after["hub"]


def test_apply_backs_the_old_project_up_once(tmp_path):
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    path = _project(tmp_path, PIMIDI_HUB)
    backup = path.with_suffix(path.suffix + ".autohub.bak")
    autohub.apply_to_project(path, autohub.build_hub(ports), ports)
    assert endpoints(json.loads(backup.read_text())["hub"]).keys() == \
        endpoints(PIMIDI_HUB).keys()
    stamp = backup.stat().st_mtime_ns
    autohub.apply_to_project(path, autohub.build_hub(ports), ports, force=True)
    assert backup.stat().st_mtime_ns == stamp   # the first hub is the one


def test_dry_run_changes_nothing(tmp_path):
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    path = _project(tmp_path, PIMIDI_HUB)
    before = path.read_text(encoding="utf-8")
    assert not autohub.apply_to_project(path, autohub.build_hub(ports), ports,
                                        dry_run=True)
    assert path.read_text(encoding="utf-8") == before


def test_apply_is_idempotent(tmp_path):
    ports = autohub.parse_proc_clients(PROC_PISOUND_KEYSTEP)
    path = _project(tmp_path, PIMIDI_HUB)
    autohub.apply_to_project(path, autohub.build_hub(ports), ports)
    fixed = path.read_text(encoding="utf-8")
    assert not autohub.apply_to_project(path, autohub.build_hub(ports), ports)
    assert path.read_text(encoding="utf-8") == fixed


# --- the unattended entry point ----------------------------------------------

def test_apply_exits_zero_when_the_project_is_missing(tmp_path, monkeypatch,
                                                     capsys):
    monkeypatch.setattr(autohub, "DISABLE_FLAG", tmp_path / "absent")
    assert autohub.main(["--apply", "--project",
                         str(tmp_path / "gone.rkproj")]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_apply_exits_zero_on_a_corrupt_project(tmp_path, monkeypatch, capsys):
    # A half-written project must not be the reason the instrument fails to
    # boot: ExecStartPre reports and gets out of the way.
    path = tmp_path / "starter.rkproj"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(autohub, "DISABLE_FLAG", tmp_path / "absent")
    assert autohub.main(["--apply", "--project", str(path),
                         "--preset", str(tmp_path / "auto.rkhub")]) == 0
    assert "left as it was" in capsys.readouterr().out


def test_the_disable_flag_stops_it(tmp_path, monkeypatch, capsys):
    flag = tmp_path / "autohub.disabled"
    flag.touch()
    monkeypatch.setattr(autohub, "DISABLE_FLAG", flag)
    path = _project(tmp_path, PIMIDI_HUB)
    before = path.read_text(encoding="utf-8")
    assert autohub.main(["--apply", "--project", str(path)]) == 0
    assert "leaving the hub alone" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == before


def test_check_mode_names_the_endpoint_that_cannot_bind(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.setattr(autohub, "read_graph",
                        lambda: autohub.parse_proc_clients(
                            PROC_PISOUND_KEYSTEP))
    path = _project(tmp_path, PIMIDI_HUB)
    assert autohub.main(["--project", str(path)]) == 0
    out = capsys.readouterr().out
    assert "no such port" in out and "din_in_a" in out
    assert "0/4 endpoints resolve" in out
    assert "Arturia KeyStep 37" in out          # the graph is printed too
