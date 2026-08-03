"""The SceneRanger engine end to end: launches, boundaries, follows,
recording, chains — and the invariant. Every test here ends with
``assert not midi.hanging()``.
"""
from __future__ import annotations

from core import commands as cmd
from core.clip import Clip, ClipNote
from core.engine import SceneRangerEngine
from core.project import Project, default_project
from rangerkit import enginebase as base
from rangerkit.events import EventKind, PPQN, TICKS_PER_BAR, note_off, \
    note_on
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks


def make_clip(*pitches, bars=1, **fields):
    c = Clip(length_ticks=bars * TICKS_PER_BAR, **fields).normalised()
    for index, pitch in enumerate(pitches):
        c = c.with_note(ClipNote(tick=index * PPQN, note=pitch,
                                 velocity=100, length_ticks=24))
    return c


def rig(project=None):
    midi = CaptureMidiIO()
    engine = SceneRangerEngine(project or default_project(), midi,
                               FakeClock())
    return engine, midi


def ons(midi, channel=None):
    return [e for _ep, e in midi.events if e.kind is EventKind.NOTE_ON
            and (channel is None or e.channel == channel)]


def stop_clean(engine, midi):
    engine.submit(cmd.StopAll())
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()


# --- launching -----------------------------------------------------------------

def test_launch_starts_the_session_and_loops():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, 64))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR * 2)
    assert engine.playing
    assert [e.data1 for e in ons(midi)] == [60, 64, 60, 64]
    stop_clean(engine, midi)


def test_empty_pad_is_a_no_op():
    engine, midi = rig()
    engine.submit(cmd.LaunchClip(track=0, scene=5))
    engine.step()
    assert not engine.playing and not midi.events
    assert not midi.hanging()


def test_bar_quantize_defers_the_switch():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    engine.grid.put(0, 1, make_clip(72))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, PPQN)                 # mid-bar
    engine.submit(cmd.LaunchClip(track=0, scene=1))
    run_ticks(engine, PPQN)                 # still this bar: no 72 yet
    assert 72 not in {e.data1 for e in ons(midi)}
    run_ticks(engine, TICKS_PER_BAR * 2)    # over the bar line
    assert 72 in {e.data1 for e in ons(midi)}
    stop_clean(engine, midi)


def test_quantize_off_switches_on_the_next_tick():
    engine, midi = rig()
    engine.submit(cmd.SetLaunchQuantize(mode="off"))
    engine.grid.put(0, 0, make_clip(60))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    engine.step()                           # drain + first tick
    engine.step()
    assert 60 in {e.data1 for e in ons(midi)}   # <5-10 ms path
    stop_clean(engine, midi)


def test_clip_switch_releases_the_outgoing_voice():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, bars=1))
    # A clip whose note is a whole bar long: sounding at every switch.
    long_clip = Clip(notes=(ClipNote(0, 48, 100, TICKS_PER_BAR * 4),),
                     length_ticks=TICKS_PER_BAR)
    engine.grid.put(0, 1, long_clip)
    engine.submit(cmd.LaunchClip(track=0, scene=1))
    run_ticks(engine, TICKS_PER_BAR // 2)
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR)        # boundary passed, 48 released
    held = {n for _ch, n in midi.hanging()}
    assert 48 not in held
    stop_clean(engine, midi)


def test_scene_launch_is_a_state_not_a_delta():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    engine.grid.put(1, 0, make_clip(64))
    engine.grid.put(0, 1, make_clip(72))    # scene 2 has only track 1
    engine.submit(cmd.LaunchScene(scene=0))
    run_ticks(engine, TICKS_PER_BAR)
    engine.submit(cmd.LaunchScene(scene=1))
    run_ticks(engine, TICKS_PER_BAR * 2)
    pitches = [e.data1 for e in ons(midi)]
    assert pitches.count(64) == 1           # track 2 stopped with scene 2
    assert pitches.count(72) == 2           # track 1 kept looping scene 2
    stop_clean(engine, midi)


# --- follow actions ------------------------------------------------------------

def test_follow_next_advances_after_its_loops():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, follow="next", follow_loops=2))
    engine.grid.put(0, 3, make_clip(72))    # "next" hops the empty rows
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR * 4 + 2)
    assert 72 in {e.data1 for e in ons(midi)}
    played = [e.data1 for e in ons(midi)]
    assert played.count(60) == 2            # exactly two loops of the first
    stop_clean(engine, midi)


def test_follow_stop_ends_the_track():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, follow="stop", follow_loops=1))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR * 3)
    assert [e.data1 for e in ons(midi)] == [60]
    stop_clean(engine, midi)


def test_follow_probability_is_seeded():
    project = default_project()
    engine1, midi1 = rig(project)
    engine2, midi2 = rig(default_project())
    for engine in (engine1, engine2):
        engine.grid.put(0, 0, make_clip(60, follow="stop", follow_loops=1,
                                        follow_probability=0.5))
        engine.grid.put(0, 1, make_clip(64))
        engine.submit(cmd.LaunchClip(track=0, scene=0))
        run_ticks(engine, TICKS_PER_BAR * 8)
    assert midi1.events == midi2.events     # same seed, same dice
    stop_clean(engine1, midi1)
    stop_clean(engine2, midi2)


# --- recording -----------------------------------------------------------------

def record(engine, pitch, hold=24):
    engine.on_midi_in("din_in", note_on(0, pitch, 100), 0)
    run_ticks(engine, hold)
    engine.on_midi_in("din_in", note_off(0, pitch), 0)
    engine.step()


def test_record_into_an_empty_slot_rounds_up_to_bars():
    engine, midi = rig()
    engine.submit(cmd.ArmSlot(track=2, scene=1))
    engine.step()
    assert engine.playing                   # arming starts the session
    record(engine, 60)
    run_ticks(engine, TICKS_PER_BAR)        # take runs past one bar
    record(engine, 64)
    engine.submit(cmd.Disarm())
    engine.step()
    clip = engine.grid.clip(2, 1)
    assert clip is not None and clip.bars == 2
    assert {n.note for n in clip.notes} == {60, 64}
    stop_clean(engine, midi)


def test_overdub_keeps_the_existing_length():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, bars=1))
    engine.submit(cmd.ArmSlot(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR + 8)
    record(engine, 67)
    engine.submit(cmd.Disarm())
    engine.step()
    clip = engine.grid.clip(0, 0)
    assert clip.bars == 1
    assert {n.note for n in clip.notes} == {60, 67}
    stop_clean(engine, midi)


def test_monitor_thru_sounds_on_the_tracks_output():
    engine, midi = rig()
    engine.grid.tracks[3] = engine.grid.tracks[3].__class__(
        dest="usb_out", channel=9)
    engine.submit(cmd.ArmSlot(track=3, scene=0))
    engine.step()
    engine.on_midi_in("din_in", note_on(0, 72, 90), 0)
    engine.step()
    thru = [e for ep, e in midi.events
            if ep == "usb_out" and e.kind is EventKind.NOTE_ON]
    assert [e.data1 for e in thru] == [72]
    engine.on_midi_in("din_in", note_off(0, 72), 0)
    engine.step()
    engine.submit(cmd.Disarm())
    engine.step()
    stop_clean(engine, midi)


def test_panic_lands_the_take_and_silences():
    engine, midi = rig()
    engine.submit(cmd.ArmSlot(track=0, scene=0))
    engine.step()
    engine.on_midi_in("din_in", note_on(0, 60, 100), 0)
    run_ticks(engine, 30)
    engine.submit(base.Panic())
    engine.step()
    assert not engine.playing
    assert not engine.recorder.recording
    assert not midi.hanging()


# --- chain / arrange -----------------------------------------------------------

def test_chain_steps_scenes_on_schedule():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    engine.grid.put(0, 1, make_clip(72))
    engine.submit(cmd.ChainAppend(scene=0, bars=1))
    engine.submit(cmd.ChainAppend(scene=1, bars=1))
    engine.submit(cmd.SetChainOn(on=True))
    run_ticks(engine, TICKS_PER_BAR * 4 + 2)
    pitches = [e.data1 for e in ons(midi)]
    assert 60 in pitches and 72 in pitches
    assert pitches[0] == 60                 # chain order held
    stop_clean(engine, midi)


def test_empty_chain_is_a_message():
    engine, midi = rig()
    engine.submit(cmd.SetChainOn(on=True))
    engine.step()
    assert "EMPTY" in engine.snapshot().message
    assert not engine.chain.on
    assert not midi.hanging()


# --- fields / pots / project ---------------------------------------------------

def test_mute_and_reroute_release_cleanly():
    engine, midi = rig()
    engine.grid.put(0, 0, Clip(notes=(ClipNote(0, 60, 100,
                                               TICKS_PER_BAR * 2),),
                               length_ticks=TICKS_PER_BAR))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR // 2)
    engine.submit(cmd.SetTrackField(track=0, name="muted", value=True))
    engine.step()
    assert not midi.hanging()               # the long note was released
    engine.submit(cmd.SetTrackField(track=0, name="muted", value=False))
    engine.submit(cmd.SetTrackField(track=0, name="channel", value=5))
    run_ticks(engine, TICKS_PER_BAR)
    stop_clean(engine, midi)


def test_clip_fields_shape_playback():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    engine.submit(cmd.SetClipField(track=0, scene=0, name="transpose",
                                   value=7))
    engine.submit(cmd.SetClipField(track=0, scene=0, name="velocity_scale",
                                   value=0.5))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR)
    fired = ons(midi)[0]
    assert fired.data1 == 67 and fired.data2 == 50
    stop_clean(engine, midi)


def test_intensity_pot_scales_the_room():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    pots = FakePots(engine.submit)
    pots.turn(1, 0.5)                       # POT_B = intensity
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR)
    assert ons(midi)[0].data2 == 50
    pots.turn(0, 0.0)                       # POT_A sweeps quantize → off
    engine.step()
    assert engine.quantize == "off"
    stop_clean(engine, midi)


def test_project_round_trip(tmp_path):
    engine, midi = rig()
    engine.grid.put(4, 2, make_clip(60, 64, follow="random"))
    engine.submit(cmd.ChainAppend(scene=2, bars=8))
    engine.step()
    path = tmp_path / "set.scproj"
    engine.capture().save(path)
    engine2, midi2 = rig(Project.load(path))
    assert engine2.grid.clip(4, 2) == engine.grid.clip(4, 2)
    assert engine2.chain.entries == [(2, 8)]
    assert not midi.hanging() and not midi2.hanging()


def test_unknown_fields_cost_a_log_line_only():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60))
    engine.submit(cmd.SetClipField(track=0, scene=0, name="warp", value=1))
    engine.submit(cmd.SetClipField(track=0, scene=0, name="notes", value=()))
    engine.submit(cmd.SetTrackField(track=99, name="muted", value=True))
    engine.submit(cmd.SetLaunchQuantize(mode="sometimes"))
    engine.step()
    assert engine.quantize == "bar"
    assert not midi.hanging()


def test_snapshot_reports_the_session():
    engine, midi = rig()
    engine.grid.put(0, 0, make_clip(60, follow="next"))
    engine.submit(cmd.LaunchClip(track=0, scene=0))
    run_ticks(engine, TICKS_PER_BAR // 2)
    s = engine.snapshot()
    assert len(s.slots) == 12 and len(s.slots[0]) == 8
    assert s.slots[0][0].filled and s.slots[0][0].playing
    assert s.slots[0][0].follow == "next"
    assert s.tracks[0].active == 0 and 0.0 < s.tracks[0].position < 1.0
    assert s.scenes_filled[0] and not s.scenes_filled[1]
    stop_clean(engine, midi)
