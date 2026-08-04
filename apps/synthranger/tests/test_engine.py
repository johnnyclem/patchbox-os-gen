"""The SynthRanger engine end to end: routing through the release book,
the internal CC contract, edits, and the invariant — proven against the
real Synth through the real bridge. Every test ends with nothing hanging,
MIDI bookings or voices.
"""
from __future__ import annotations

import numpy as np

from core import commands as cmd
from core.engine import SynthRangerEngine
from core.project import Project, default_project
from core.voices import Synth
from rangerkit import enginebase as base
from rangerkit.audio.bridge import SynthMidiBridge
from rangerkit.events import EventKind, note_off, note_on
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks


def rig(project=None):
    capture = CaptureMidiIO()
    synth = Synth()
    engine = SynthRangerEngine(project or default_project(),
                               SynthMidiBridge(capture, synth),
                               FakeClock())
    return engine, capture, synth


def ons(capture, channel=None):
    return [e for _ep, e in capture.events
            if e.kind is EventKind.NOTE_ON
            and (channel is None or e.channel == channel)]


def stop_clean(engine, capture, synth):
    engine.submit(base.Panic())
    engine.step()
    assert not capture.hanging()
    assert not synth.hanging_voices()


# --- routing -------------------------------------------------------------------

def test_touch_key_sounds_the_selected_part_and_releases():
    engine, capture, synth = rig()
    engine.submit(cmd.SelectPart(part=2))
    engine.submit(cmd.KeyDown(note=60))
    engine.step()
    assert synth.hanging_voices() == {(2, 60)}
    assert np.sqrt(np.mean(np.square(synth.render(2048)))) > 0.001
    engine.submit(cmd.KeyUp(note=60))
    engine.step()
    assert not synth.hanging_voices()
    assert not capture.hanging()


def test_midi_in_routes_by_part_listen_channel():
    engine, capture, synth = rig()
    engine.on_midi_in("din_in", note_on(3, 52, 96), 0)
    engine.step()
    assert synth.hanging_voices() == {(3, 52)}      # part 3 listens on 3
    engine.on_midi_in("din_in", note_on(9, 52, 96), 0)
    engine.step()
    assert len(synth.hanging_voices()) == 1         # no listener: dropped
    engine.on_midi_in("din_in", note_off(3, 52), 0)
    engine.step()
    assert not synth.hanging_voices()
    stop_clean(engine, capture, synth)


def test_muted_part_takes_no_notes_and_mute_releases():
    engine, capture, synth = rig()
    engine.submit(cmd.KeyDown(note=60))
    engine.step()
    assert synth.hanging_voices()
    engine.submit(cmd.SetPartField(part=0, name="muted", value=True))
    engine.step()
    assert not synth.hanging_voices()               # released at the mute
    engine.submit(cmd.KeyDown(note=64))
    engine.step()
    assert not synth.hanging_voices()               # and deaf while muted
    stop_clean(engine, capture, synth)


def test_stop_and_panic_release_everything():
    engine, capture, synth = rig()
    for note in (48, 55, 60, 64):
        engine.submit(cmd.KeyDown(note=note))
    run_ticks(engine, 8)
    assert len(synth.hanging_voices()) == 4
    stop_clean(engine, capture, synth)


# --- the CC contract -----------------------------------------------------------

def test_xy_pad_travels_as_cc_16_17_on_the_selected_part():
    engine, capture, synth = rig()
    engine.submit(cmd.SelectPart(part=1))
    engine.submit(cmd.SetXY(x=1.0, y=0.0))
    engine.step()
    sent = [(e.channel, e.data1, e.data2) for _ep, e in capture.events
            if e.kind is EventKind.CC]
    assert not sent                                  # internal-only: peeled
    assert synth._controls[1]["xy_x"] == 1.0
    assert synth._controls[1]["xy_y"] == 0.0
    assert engine.snapshot().xy == (1.0, 0.0)
    stop_clean(engine, capture, synth)


def test_incoming_mod_wheel_reaches_the_synth():
    engine, capture, synth = rig()
    from rangerkit.events import MidiEvent
    engine.on_midi_in("din_in", MidiEvent(EventKind.CC, 0, 2, 1, 127), 0)
    engine.step()
    assert synth._controls[2]["mod_wheel"] == 1.0
    stop_clean(engine, capture, synth)


def test_pot_a_sweeps_cutoff_pot_b_morphs():
    engine, capture, synth = rig()
    pots = FakePots(engine.submit)
    pots.turn(0, 1.0)
    pots.turn(1, 0.6)
    engine.step()
    assert synth._controls[0]["cutoff_offset"] > 0.45
    assert abs(engine.parts[0].morph - 0.6) < 0.01
    stop_clean(engine, capture, synth)


# --- editing -------------------------------------------------------------------

def test_patch_edits_bump_the_rev_and_reach_the_effective_patch():
    engine, capture, synth = rig()
    engine.step()                                    # publish a snapshot
    rev = engine.snapshot().parts_rev
    engine.submit(cmd.SetPatchField(part=0, name="engine", value="pd"))
    engine.submit(cmd.SetPatchField(part=0, name="cutoff", value=0.3))
    engine.step()
    snapshot = engine.snapshot()
    assert snapshot.parts_rev > rev
    assert snapshot.parts[0].patch["engine"] == "pd"
    assert abs(snapshot.parts[0].patch["cutoff"] - 0.3) < 1e-9
    stop_clean(engine, capture, synth)


def test_morph_between_a_and_b_shows_in_the_snapshot():
    engine, capture, synth = rig()
    engine.submit(cmd.SetPatchState(
        part=0, params={"name": "TARGET", "cutoff": 0.0}, slot_b=True))
    engine.submit(cmd.SetPartField(part=0, name="morph", value=0.5))
    engine.step()
    view = engine.snapshot().parts[0]
    assert view.name_b == "TARGET"
    assert abs(view.patch["cutoff"] - 0.4) < 1e-6   # (0.8 + 0.0) / 2
    stop_clean(engine, capture, synth)


def test_copy_a_to_b_freezes_the_current_sound():
    engine, capture, synth = rig()
    engine.submit(cmd.SetPatchState(
        part=1, params={"name": "FAR", "cutoff": 0.0}, slot_b=True))
    engine.submit(cmd.SetPartField(part=1, name="morph", value=1.0))
    engine.submit(cmd.CopyAToB(part=1))
    engine.step()
    part = engine.parts[1]
    assert part.morph == 0.0
    assert part.patch_b.cutoff == 0.0               # B = what was sounding
    stop_clean(engine, capture, synth)


def test_mod_slot_edits_validate():
    engine, capture, synth = rig()
    engine.submit(cmd.SetModSlot(part=0, slot=0, source="lfo",
                                 dest="pitch", amount=0.4))
    engine.submit(cmd.SetModSlot(part=0, slot=1, source="bogus",
                                 dest="pitch", amount=1.0))
    engine.step()
    mods = engine.parts[0].mods
    assert (mods[0].source, mods[0].dest) == ("lfo", "pitch")
    assert mods[1].source == "xy_y"                 # bogus edit ignored
    stop_clean(engine, capture, synth)


# --- state ---------------------------------------------------------------------

def test_project_round_trip_is_faithful(tmp_path):
    engine, capture, synth = rig()
    engine.submit(cmd.SetPatchField(part=0, name="engine",
                                    value="wavetable"))
    engine.submit(cmd.SetPartField(part=2, name="level", value=0.5))
    engine.submit(cmd.SetModSlot(part=1, slot=0, source="lfo",
                                 dest="timbre", amount=-0.7))
    engine.step()
    engine.capture().save(tmp_path / "rig.syproj")
    restored, capture2, synth2 = rig(Project.load(tmp_path / "rig.syproj"))
    assert restored.parts == engine.parts
    restored.submit(cmd.KeyDown(note=60))
    restored.step()
    assert synth2.hanging_voices() == {(0, 60)}
    stop_clean(restored, capture2, synth2)


def test_recall_project_state_releases_first():
    engine, capture, synth = rig()
    engine.submit(cmd.KeyDown(note=60))
    engine.step()
    engine.submit(cmd.RecallProjectState(params={}))
    engine.step()
    assert not capture.hanging()
    assert not synth.hanging_voices()
    assert engine.parts[0].patch.name == "INIT"


def test_channel_reassignment_releases_the_old_plumbing():
    engine, capture, synth = rig()
    engine.submit(cmd.KeyDown(note=60))
    engine.step()
    engine.submit(cmd.SetPartField(part=0, name="channel", value=7))
    engine.step()
    assert not synth.hanging_voices()
    engine.on_midi_in("din_in", note_on(7, 50, 90), 0)
    engine.step()
    assert synth.hanging_voices() == {(0, 50)}      # new listen channel
    stop_clean(engine, capture, synth)
