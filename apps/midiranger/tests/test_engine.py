"""The MidiRanger engine end to end: thru, arps, echoes, scenes, and the
invariant. Every test here ends with ``assert not midi.hanging()``.
"""
from __future__ import annotations

from core import commands as cmd
from core.engine import MidiRangerEngine, THRU_SAFETY_TICKS
from core.project import Project, default_project
from rangerkit import enginebase as base
from rangerkit.events import (EventKind, MidiEvent, PPQN, TICKS_PER_BAR,
                              note_off, note_on)
from rangerkit.routing import Route
from rangerkit.testkit import CaptureMidiIO, FakeClock, run_ticks


def rig(project=None):
    midi = CaptureMidiIO()
    engine = MidiRangerEngine(project or default_project(), midi, FakeClock())
    return engine, midi


def press(engine, note, velocity=100, endpoint="din_in", channel=0):
    engine.on_midi_in("" + endpoint, note_on(channel, note, velocity), 0)


def lift(engine, note, endpoint="din_in", channel=0):
    engine.on_midi_in(endpoint, note_off(channel, note), 0)


def sent(midi, endpoint):
    return [e for ep, e in midi.events if ep == endpoint]


# --- thru ----------------------------------------------------------------------

def test_thru_is_immediate_and_released_by_the_player():
    engine, midi = rig()
    press(engine, 60)
    engine.step()                           # drain — the <5 ms path
    ons = [e for e in sent(midi, "din_out")
           if e.kind is EventKind.NOTE_ON]
    assert [e.data1 for e in ons] == [60]
    lift(engine, 60)
    engine.step()
    assert not midi.hanging()


def test_thru_fans_out_to_every_route_target():
    project = default_project()
    project.params["routes"].append(
        {"src": "din_in", "dst": "usb_out", "channel": -1, "to_channel": 2})
    engine, midi = rig(project)
    press(engine, 60)
    engine.step()
    assert [e.data1 for e in sent(midi, "din_out")] == [60]
    usb = sent(midi, "usb_out")
    assert [(e.data1, e.channel) for e in usb] == [(60, 2)]
    lift(engine, 60)
    engine.step()
    assert not midi.hanging()


def test_unrouted_input_goes_nowhere():
    engine, midi = rig(Project())           # no routes at all
    press(engine, 60)
    engine.step()
    assert not midi.events
    assert not midi.hanging()


def test_thru_safety_net_releases_a_dead_input():
    engine, midi = rig()
    press(engine, 60)
    engine.step()
    # The player's note-off never arrives (cable yanked). The book pays.
    engine.submit(base.Play())
    run_ticks(engine, THRU_SAFETY_TICKS + 2)
    assert not midi.hanging()


def test_cc_passes_straight_through_rewritten():
    project = default_project()
    project.params["routes"] = [
        {"src": "din_in", "dst": "usb_out", "channel": -1, "to_channel": 5}]
    engine, midi = rig(project)
    engine.on_midi_in("din_in", MidiEvent(EventKind.CC, 0, 0, 74, 42), 0)
    engine.step()
    out = sent(midi, "usb_out")
    assert [(e.kind, e.channel, e.data1, e.data2) for e in out] == \
        [(EventKind.CC, 5, 74, 42)]
    assert not midi.hanging()


def test_quantize_and_harmonize_shape_the_thru_voice():
    project = default_project()
    project.params["quantizer"] = {"enabled": True, "root": 0,
                                   "scale": "major"}
    project.params["harmonizer"] = {"mode": "triad", "root": 0,
                                    "scale": "major"}
    engine, midi = rig(project)
    press(engine, 61)                       # C# → C, plus diatonic E and G
    engine.step()
    ons = sorted(e.data1 for e in sent(midi, "din_out")
                 if e.kind is EventKind.NOTE_ON)
    assert ons == [60, 64, 67]
    lift(engine, 61)
    engine.step()
    assert not midi.hanging()


def test_removing_a_route_releases_what_traveled_it():
    engine, midi = rig()
    press(engine, 60)
    engine.step()
    engine.submit(cmd.ToggleRoute(Route(src="din_in", dst="din_out")))
    engine.step()
    assert not midi.hanging()               # released by the route change
    lift(engine, 60)                        # stale note-off is a no-op
    engine.step()
    assert not midi.hanging()


# --- echoes and scheduling -----------------------------------------------------

def test_echo_fires_later_even_while_stopped():
    project = default_project()
    project.params["fx"] = {"echo_repeats": 2, "echo_ticks": PPQN,
                            "echo_decay": 0.5}
    engine, midi = rig(project)
    press(engine, 60)
    engine.step()
    assert len(sent(midi, "din_out")) == 1  # the played note, now
    run_ticks(engine, PPQN * 2 + 2)         # transport never started
    ons = [e for e in sent(midi, "din_out") if e.kind is EventKind.NOTE_ON]
    assert [e.data1 for e in ons] == [60, 60, 60]
    assert [e.data2 for e in ons] == [100, 50, 25]
    lift(engine, 60)
    run_ticks(engine, PPQN)                 # echo lengths run out
    assert not midi.hanging()


def test_stop_cancels_pending_echoes():
    project = default_project()
    project.params["fx"] = {"echo_repeats": 4, "echo_ticks": PPQN}
    engine, midi = rig(project)
    engine.submit(base.Play())
    press(engine, 60)
    run_ticks(engine, 4)
    engine.submit(base.Stop())
    engine.step()
    before = len(midi.events)
    run_ticks(engine, PPQN * 6)
    after_ons = [e for _ep, e in midi.events[before:]
                 if e.kind is EventKind.NOTE_ON]
    assert not after_ons                    # nothing ghosted in after stop
    assert not midi.hanging()


# --- arps ----------------------------------------------------------------------

def arp_project(**arp_overrides):
    project = default_project()
    project.params["arps"] = [
        {"enabled": True, "source": "din_in", "channel_in": -1,
         "dest": "usb_out", "channel_out": 3, "rate": PPQN // 4,
         "gate": 0.5, "pattern": "up", **arp_overrides}]
    return project


def test_arp_consumes_input_and_steps_the_grid():
    engine, midi = rig(arp_project())
    engine.submit(base.Play())
    press(engine, 60)
    press(engine, 64)
    run_ticks(engine, PPQN)                 # one beat = 4 sixteenth steps
    assert not sent(midi, "din_out")        # consumed: no thru
    ons = [e for e in sent(midi, "usb_out") if e.kind is EventKind.NOTE_ON]
    assert [e.data1 for e in ons] == [60, 64, 60, 64]
    assert all(e.channel == 3 for e in ons)
    lift(engine, 60)
    lift(engine, 64)
    run_ticks(engine, PPQN)
    assert not midi.hanging()


def test_arp_gate_releases_between_steps():
    engine, midi = rig(arp_project())
    engine.submit(base.Play())
    press(engine, 60)
    run_ticks(engine, PPQN // 4)            # exactly one step
    offs = [e for e in sent(midi, "usb_out")
            if e.kind is EventKind.NOTE_OFF]
    assert len(offs) == 1                   # gate 0.5 closed inside the step
    lift(engine, 60)
    run_ticks(engine, PPQN)
    assert not midi.hanging()


def test_arp_ratchet_fires_inside_the_step():
    engine, midi = rig(arp_project(ratchet=2, gate=1.0))
    engine.submit(base.Play())
    press(engine, 60)
    run_ticks(engine, PPQN // 4)
    ons = [e for e in sent(midi, "usb_out") if e.kind is EventKind.NOTE_ON]
    assert len(ons) == 2                    # two hits, one step
    lift(engine, 60)
    run_ticks(engine, PPQN)
    assert not midi.hanging()


def test_arps_stress_never_strands_under_churn():
    """The release-book stress the plan calls for: notes in and out under a
    running arp, scene-less, across bars."""
    engine, midi = rig(arp_project(ratchet=3, octaves=2, gate=0.9))
    engine.submit(base.Play())
    notes = [57, 60, 62, 64, 65, 67, 69]
    for bar in range(4):
        for i, note in enumerate(notes):
            press(engine, note)
            run_ticks(engine, 7 + i)
            if (bar + i) % 2:
                lift(engine, note)
                run_ticks(engine, 3)
        run_ticks(engine, TICKS_PER_BAR // 2)
        for note in notes:
            lift(engine, note)
        run_ticks(engine, 11)
    run_ticks(engine, TICKS_PER_BAR)
    assert not midi.hanging()


def test_panic_clears_arps_schedule_and_thru():
    engine, midi = rig(arp_project())
    engine.submit(base.Play())
    press(engine, 60)
    run_ticks(engine, 10)
    engine.submit(base.Panic())
    engine.step()
    assert not engine.playing
    run_ticks(engine, TICKS_PER_BAR)        # silence after panic
    late = [e for _ep, e in midi.events[-1:] if e.kind is EventKind.NOTE_ON]
    assert not late
    assert not midi.hanging()


# --- bypass --------------------------------------------------------------------

def test_bypass_routes_raw_and_disarms_the_rack():
    project = arp_project()
    project.params["quantizer"] = {"enabled": True}
    engine, midi = rig(project)
    engine.submit(cmd.SetBypass(on=True))
    engine.submit(base.Play())
    press(engine, 61)                       # would be consumed or quantized
    run_ticks(engine, PPQN)
    assert not sent(midi, "usb_out")        # arp disarmed
    ons = [e for e in sent(midi, "din_out") if e.kind is EventKind.NOTE_ON]
    assert [e.data1 for e in ons] == [61]   # raw, unquantized
    lift(engine, 61)
    engine.step()
    assert not midi.hanging()


# --- LFOs ----------------------------------------------------------------------

def test_lfo_emits_cc_on_the_grid_while_playing():
    project = default_project()
    project.params["lfos"] = [
        {"enabled": True, "shape": "saw", "period": PPQN,
         "cc": 74, "channel": 1, "dest": "din_out"}]
    engine, midi = rig(project)
    run_ticks(engine, PPQN)                 # stopped: LFOs are quiet
    assert not [e for e in sent(midi, "din_out")
                if e.kind is EventKind.CC]
    engine.submit(base.Play())
    run_ticks(engine, PPQN)
    ccs = [e for e in sent(midi, "din_out") if e.kind is EventKind.CC]
    assert ccs and all(e.data1 == 74 and e.channel == 1 for e in ccs)
    assert len({e.data2 for e in ccs}) > 4  # actually sweeping
    assert not midi.hanging()


# --- scenes --------------------------------------------------------------------

def test_scene_save_recall_round_trip():
    engine, midi = rig()
    engine.submit(cmd.SetQuantizerField(name="enabled", value=True))
    engine.submit(cmd.SaveScene(slot=0))
    engine.step()
    engine.submit(cmd.SetQuantizerField(name="enabled", value=False))
    engine.submit(cmd.SetHarmonizerField(name="mode", value="octave"))
    engine.submit(cmd.SaveScene(slot=1))
    engine.step()
    engine.submit(cmd.RecallScene(slot=0))
    engine.step()
    assert engine.quantizer.enabled and engine.harmonizer.mode == "off"
    engine.submit(cmd.RecallScene(slot=1))
    engine.step()
    assert not engine.quantizer.enabled
    assert engine.harmonizer.mode == "octave"
    assert not midi.hanging()


def test_recall_empty_slot_is_a_message_not_a_crash():
    engine, midi = rig()
    engine.submit(cmd.RecallScene(slot=5))
    engine.step()
    assert "EMPTY" in engine.snapshot().message
    assert not midi.hanging()


def test_scene_recall_mid_notes_strands_nothing():
    engine, midi = rig()
    engine.submit(cmd.SaveScene(slot=0))
    engine.step()
    press(engine, 60)
    press(engine, 64)
    engine.step()
    engine.submit(cmd.RecallScene(slot=0))
    engine.step()
    assert not midi.hanging()               # recall released the thru notes
    lift(engine, 60)
    lift(engine, 64)
    engine.step()
    assert not midi.hanging()


def test_morph_blends_numeric_params():
    engine, midi = rig()
    engine.submit(cmd.SetFxField(name="echo_decay", value=0.2))
    engine.submit(cmd.SaveScene(slot=0))
    engine.submit(cmd.SetFxField(name="echo_decay", value=1.0))
    engine.submit(cmd.SaveScene(slot=1))
    engine.submit(cmd.Morph(slot_a=0, slot_b=1, t=0.5))
    engine.step()
    assert abs(engine.fx.echo_decay - 0.6) < 1e-9
    assert engine.snapshot().morph == (0, 1, 0.5)
    assert not midi.hanging()


# --- commands and snapshot -----------------------------------------------------

def test_unknown_field_names_cost_a_log_line_only():
    engine, midi = rig()
    engine.submit(cmd.SetArpField(index=0, name="warp", value=9))
    engine.submit(cmd.SetFxField(name="flux", value=1))
    engine.submit(cmd.SetArpField(index=99, name="gate", value=0.5))
    engine.step()                           # none of these may raise
    assert not midi.hanging()


def test_snapshot_reports_the_rack():
    project = arp_project()
    engine, midi = rig(project)
    press(engine, 60)
    engine.step()
    snapshot = engine.snapshot()
    assert len(snapshot.arps) == 4 and snapshot.arps[0].enabled
    assert snapshot.arps[0].held == (60,)
    assert len(snapshot.lfos) == 4
    assert snapshot.scenes_occupied == (False,) * 8
    assert ("din_in", 1) in snapshot.activity_in
    assert snapshot.project_name == "untitled"
    lift(engine, 60)
    engine.step()
    assert not midi.hanging()


def test_capture_round_trips_through_project(tmp_path):
    engine, midi = rig()
    engine.submit(cmd.SetHarmonizerField(name="mode", value="power"))
    engine.submit(cmd.SaveScene(slot=2))
    engine.step()
    saved = engine.capture()
    path = tmp_path / "set.mrproj"
    saved.save(path)
    loaded = Project.load(path)
    engine2, midi2 = rig(loaded)
    assert engine2.harmonizer.mode == "power"
    assert engine2.scenes.occupied()[2]
    assert not midi.hanging() and not midi2.hanging()


# --- pots ----------------------------------------------------------------------

def test_pots_turn_the_default_hot_params():
    from rangerkit.testkit import FakePots
    engine, midi = rig(arp_project())
    pots = FakePots(engine.submit)
    pots.turn(0, 0.25)                      # POT_A -> arp probability
    pots.turn(1, 1.0)                       # POT_B -> humanize
    engine.step()
    assert abs(engine.arps[0].params.probability - 0.25) < 0.01
    assert engine.fx.humanize_timing > 0
    assert engine.fx.humanize_velocity > 0
    assert not midi.hanging()


def test_pot_map_from_config_overrides():
    from rangerkit.configbase import PotsConfig, RangerConfig
    from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots
    config = RangerConfig(pots=PotsConfig(map={"POT_A": "echo_decay",
                                               "POT_B": "warp_field"}))
    midi = CaptureMidiIO()
    engine = MidiRangerEngine(default_project(), midi, FakeClock(),
                              config=config)
    pots = FakePots(engine.submit)
    pots.turn(0, 1.0)
    pots.turn(1, 0.0)                       # unknown target: logged, ignored
    engine.step()
    assert engine.fx.echo_decay == 1.0
    assert not midi.hanging()
