"""The GrooveRanger engine end to end: schedules through the release book,
the internal CC contract, fills, songs, recording — and the invariant.
Every test here ends with ``assert not midi.hanging()``.
"""
from __future__ import annotations

from core import commands as cmd
from core.engine import GrooveRangerEngine
from core.project import Project, default_project
from core.sequencer import STEP_TICKS
from rangerkit import enginebase as base
from rangerkit.events import EventKind
from rangerkit.routing import INTERNAL
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks

PASS = 16 * STEP_TICKS                    # one full default pattern


def rig(project=None, midi=None):
    midi = midi if midi is not None else CaptureMidiIO()
    engine = GrooveRangerEngine(project or Project(), midi, FakeClock())
    return engine, midi


def ons(midi, endpoint=None, channel=None):
    return [(ep, e) for ep, e in midi.events if e.kind is EventKind.NOTE_ON
            and (endpoint is None or ep == endpoint)
            and (channel is None or e.channel == channel)]


def ccs(midi, channel=None, number=None):
    return [(ep, e) for ep, e in midi.events if e.kind is EventKind.CC
            and (channel is None or e.channel == channel)
            and (number is None or e.data1 == number)]


def play(engine):
    # Submit only: the first tick of the following run_ticks drains it, so
    # a run of PASS ticks is exactly one pattern pass.
    engine.submit(base.Play())


def stop_clean(engine, midi):
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()


# --- emission ------------------------------------------------------------------

def test_a_step_fires_on_its_pad_channel_internally():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.ToggleStep(pad=4, step=8))
    play(engine)
    run_ticks(engine, PASS)
    hits = ons(midi, endpoint=INTERNAL)
    assert [(e.channel, e.data1) for _ep, e in hits] == [(0, 36), (4, 42)]
    stop_clean(engine, midi)


def test_default_project_grooves_and_releases():
    engine, midi = rig(default_project())
    play(engine)
    run_ticks(engine, PASS * 2)
    kicks = ons(midi, channel=0)
    assert len(kicks) == 8                          # 4 quarters × 2 passes
    stop_clean(engine, midi)


def test_external_dest_uses_the_kit_channel_and_note():
    engine, midi = rig()
    engine.submit(cmd.SetKitField(name="dest", value="din_out"))
    engine.submit(cmd.SetKitField(name="channel", value=9))
    engine.submit(cmd.ToggleStep(pad=1, step=0))
    play(engine)
    run_ticks(engine, PASS)
    hits = ons(midi, endpoint="din_out")
    assert [(e.channel, e.data1) for _ep, e in hits] == [(9, 38)]
    assert not ons(midi, endpoint=INTERNAL)
    stop_clean(engine, midi)


def test_ratchets_multiply_and_release():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=2, step=0))
    engine.submit(cmd.SetStepField(pad=2, step=0, name="ratchet", value=4))
    play(engine)
    run_ticks(engine, PASS)
    assert len(ons(midi, channel=2)) == 4
    stop_clean(engine, midi)


def test_plocks_travel_as_ccs_right_before_the_hit():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.SetStepLock(pad=0, step=0, name="tune", value=12.0))
    engine.submit(cmd.SetStepLock(pad=0, step=0, name="pan", value=-1.0))
    play(engine)
    run_ticks(engine, 2)
    stream = [(ep, e.kind, e.data1, e.data2) for ep, e in midi.events
              if ep == INTERNAL and e.channel == 0]
    cc16 = [s for s in stream if s[1] is EventKind.CC and s[2] == 16]
    assert cc16 == [(INTERNAL, EventKind.CC, 16, 127)]
    note_at = next(i for i, s in enumerate(stream)
                   if s[1] is EventKind.NOTE_ON)
    assert all(stream.index(s) < note_at for s in cc16)
    stop_clean(engine, midi)


def test_external_dest_suppresses_plock_ccs():
    engine, midi = rig()
    engine.submit(cmd.SetKitField(name="dest", value="din_out"))
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.SetStepLock(pad=0, step=0, name="tune", value=12.0))
    play(engine)
    run_ticks(engine, PASS)
    assert not [e for ep, e in midi.events
                if ep == "din_out" and e.kind is EventKind.CC
                and e.data1 == 16]
    stop_clean(engine, midi)


# --- conditions, probability, fills --------------------------------------------

def test_one_in_two_fires_alternate_passes():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=3, step=0))
    engine.submit(cmd.SetStepField(pad=3, step=0, name="cond",
                                   value="2:2"))
    play(engine)
    run_ticks(engine, PASS * 4)
    assert len(ons(midi, channel=3)) == 2           # passes 1 and 3
    stop_clean(engine, midi)


def test_fill_steps_wait_for_the_fill_pass():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=2, step=0))
    engine.submit(cmd.SetStepField(pad=2, step=0, name="cond",
                                   value="fill"))
    play(engine)
    run_ticks(engine, PASS)
    assert not ons(midi, channel=2)
    engine.submit(cmd.QueueFill())                   # pressed during pass 1
    run_ticks(engine, PASS)                          # …lands at its end
    assert not ons(midi, channel=2)
    run_ticks(engine, PASS)                          # pass 2 is the fill
    assert len(ons(midi, channel=2)) == 1
    run_ticks(engine, PASS)                          # fill expired
    assert len(ons(midi, channel=2)) == 1
    stop_clean(engine, midi)


def test_probability_is_deterministic_across_twin_engines():
    project = Project()
    streams = []
    for _ in range(2):
        engine, midi = rig(project)
        engine.submit(cmd.ToggleStep(pad=0, step=0))
        engine.submit(cmd.SetStepField(pad=0, step=0, name="prob",
                                       value=0.5))
        engine.submit(cmd.ToggleStep(pad=5, step=8))
        engine.submit(cmd.SetStepField(pad=5, step=8, name="prob",
                                       value=0.3))
        play(engine)
        run_ticks(engine, PASS * 8)
        streams.append([(ep, e.kind, e.channel, e.data1, e.data2)
                        for ep, e in midi.events])
        stop_clean(engine, midi)
    assert streams[0] == streams[1]
    on_count = sum(1 for s in streams[0] if s[1] is EventKind.NOTE_ON)
    assert 0 < on_count < 16                         # the dice actually roll


# --- mutes, solos, groups ------------------------------------------------------

def test_mute_silences_and_releases_mid_note():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    play(engine)
    run_ticks(engine, 3)                             # note sounding (12 long)
    assert midi.hanging()
    engine.submit(cmd.ToggleMute(pad=0))
    engine.step()
    assert not midi.hanging()                        # released at the mute
    run_ticks(engine, PASS)
    assert len(ons(midi, channel=0)) == 1            # no more hits
    stop_clean(engine, midi)


def test_solo_isolates_a_pad():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.ToggleStep(pad=1, step=4))
    engine.submit(cmd.ToggleSolo(pad=1))
    play(engine)
    run_ticks(engine, PASS)
    assert not ons(midi, channel=0) and len(ons(midi, channel=1)) == 1
    stop_clean(engine, midi)


def test_mute_group_toggles_the_hat_family():
    engine, midi = rig()                             # rk909: pads 4,5 group 1
    engine.submit(cmd.ToggleStep(pad=4, step=0))
    engine.submit(cmd.ToggleStep(pad=5, step=4))
    engine.submit(cmd.MuteGroup(group=1))
    play(engine)
    run_ticks(engine, PASS)
    assert not ons(midi)
    engine.submit(cmd.MuteGroup(group=1))            # lift
    run_ticks(engine, PASS)
    assert len(ons(midi)) == 2
    stop_clean(engine, midi)


# --- patterns, songs -----------------------------------------------------------

def test_pattern_switch_waits_for_pass_end():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    play(engine)
    run_ticks(engine, 10)
    engine.submit(cmd.SelectPattern(index=1))
    engine.step()
    assert engine.snapshot().queued == 1
    assert engine.snapshot().pattern_index == 0
    run_ticks(engine, PASS)
    assert engine.snapshot().pattern_index == 1
    assert engine.snapshot().queued == -1
    run_ticks(engine, PASS)
    assert len(ons(midi, channel=0)) == 1            # pattern 1 is empty
    stop_clean(engine, midi)


def test_stopped_pattern_switch_is_immediate():
    engine, midi = rig()
    engine.submit(cmd.SelectPattern(index=5))
    engine.step()
    assert engine.snapshot().pattern_index == 5
    assert not midi.hanging()


def test_song_chain_presses_the_buttons():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))     # pattern 0: kick
    engine.submit(cmd.SelectPattern(index=1))
    engine.submit(cmd.ToggleStep(pad=1, step=0))     # pattern 1: snare
    engine.submit(cmd.ChainAppend(pattern=0, passes=1))
    engine.submit(cmd.ChainAppend(pattern=1, passes=1))
    engine.submit(cmd.SetChainOn(on=True))
    play(engine)
    run_ticks(engine, PASS * 4)
    kinds = [e.channel for _ep, e in ons(midi)]
    assert kinds == [0, 1, 0, 1]                     # alternating entries
    stop_clean(engine, midi)


def test_copy_pattern_and_length():
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.CopyPattern(src=0, dst=2))
    engine.submit(cmd.SelectPattern(index=2))
    engine.submit(cmd.SetPatternLength(steps=8))
    play(engine)
    run_ticks(engine, 8 * STEP_TICKS * 2)
    assert len(ons(midi, channel=0)) == 2            # 8-step pass, twice
    stop_clean(engine, midi)


# --- performing ----------------------------------------------------------------

def test_pad_hit_sounds_with_the_transport_stopped():
    engine, midi = rig()
    engine.submit(cmd.PadHit(pad=7, vel=99))
    engine.step()
    assert [(e.channel, e.data2) for _ep, e in ons(midi)] == [(7, 99)]
    assert midi.hanging()
    run_ticks(engine, STEP_TICKS)                    # FREE_RUN releases it
    assert not midi.hanging()


def test_recording_writes_quantized_hits():
    engine, midi = rig()
    engine.submit(base.SetRecord(on=True))
    play(engine)
    run_ticks(engine, STEP_TICKS * 4 + 2)            # just past step 4
    engine.submit(cmd.PadHit(pad=1, vel=88))
    run_ticks(engine, PASS)
    view = engine.snapshot().pattern[1]
    assert view[4].on and view[4].vel == 88
    assert len(ons(midi, channel=1)) >= 2            # audition + replay
    stop_clean(engine, midi)


def test_external_note_in_plays_and_records_a_pad():
    engine, midi = rig()
    engine.submit(base.SetRecord(on=True))
    play(engine)
    from rangerkit.events import note_on
    run_ticks(engine, 3)                             # a hair behind step 0
    midi.events.clear()
    engine.on_midi_in("din_in", note_on(0, 38, 105), 0)
    engine.step()
    assert [(e.channel, e.data1) for _ep, e in ons(midi)] == [(1, 38)]
    run_ticks(engine, PASS)                          # replays next pass
    assert engine.snapshot().pattern[1][0].on
    assert len(ons(midi, channel=1)) == 2
    stop_clean(engine, midi)


# --- mixer / master ------------------------------------------------------------

def test_mixer_and_master_travel_as_ccs():
    engine, midi = rig()
    midi.events.clear()
    engine.submit(cmd.SetMixerLevel(pad=3, value=0.5))
    engine.submit(cmd.SetMasterField(name="filter", value=0.25))
    engine.submit(cmd.SetMasterField(name="reverb", value=1.0))
    engine.step()
    assert ccs(midi, channel=3, number=7)[0][1].data2 == 50
    assert ccs(midi, channel=15, number=74)[0][1].data2 == 32
    assert ccs(midi, channel=15, number=91)[0][1].data2 == 127
    assert not midi.hanging()


def test_boot_syncs_the_whole_mixer():
    engine, midi = rig()
    assert len(ccs(midi, number=7)) == 13            # 12 pads + master
    assert ccs(midi, channel=15, number=85)          # delay division too
    assert not midi.hanging()


# --- pots, recall, round trip --------------------------------------------------

def test_pot_sweeps_leave_nothing_hanging():
    engine, midi = rig(default_project())
    play(engine)
    pots = FakePots(engine.submit)
    for value in (0.0, 0.3, 0.7, 1.0):
        pots.turn(0, value)
        pots.turn(1, value)
        run_ticks(engine, STEP_TICKS)
    assert ccs(midi, channel=15, number=74)          # pot A drove the filter
    assert engine.seq.swing > 0.7                    # pot B drove swing
    stop_clean(engine, midi)


def test_project_round_trip_is_faithful(tmp_path):
    engine, midi = rig()
    engine.submit(cmd.ToggleStep(pad=0, step=0))
    engine.submit(cmd.SetStepLock(pad=0, step=0, name="filter", value=0.3))
    engine.submit(cmd.SetSwing(value=0.66))
    engine.submit(cmd.SetPadField(pad=0, name="tune", value=-3.0))
    engine.submit(cmd.SetMixerLevel(pad=0, value=0.8))
    engine.submit(cmd.ChainAppend(pattern=0, passes=2))
    engine.step()
    engine.capture().save(tmp_path / "beat.grproj")
    restored, midi2 = rig(Project.load(tmp_path / "beat.grproj"))
    assert restored.seq.patterns == engine.seq.patterns
    assert restored.seq.swing == 0.66
    assert restored.kit.pads[0].tune == -3.0
    assert restored.mixer.levels[0] == 0.8
    assert restored.chain.entries == [(0, 2)]
    play(restored)
    run_ticks(restored, PASS)
    assert len(ons(midi2, channel=0)) == 1
    stop_clean(restored, midi2)


def test_recall_project_state_releases_first():
    engine, midi = rig(default_project())
    play(engine)
    run_ticks(engine, 3)
    engine.submit(cmd.RecallProjectState(params={}))
    engine.step()
    assert not midi.hanging()
    assert engine.snapshot().pattern[0][0].on is False
    stop_clean(engine, midi)


def test_panic_from_a_storm_of_everything():
    engine, midi = rig(default_project())
    play(engine)
    for burst in range(4):
        engine.submit(cmd.PadHit(pad=burst, vel=120))
        engine.submit(cmd.QueueFill())
        engine.submit(cmd.SelectPattern(index=burst % 8))
        run_ticks(engine, 7)
    engine.submit(base.Panic())
    engine.step()
    assert not midi.hanging()


# --- the whole rig -------------------------------------------------------------

def test_engine_bridge_sampler_end_to_end():
    """The release book releases *voices*: engine → SynthMidiBridge →
    Sampler, audio rendered between ticks, everything clean at stop."""
    import numpy as np
    from pathlib import Path
    from rangerkit.audio.bridge import SynthMidiBridge
    from core.kit import load_kit
    from core.sampler import Sampler

    kit_dir = Path(__file__).resolve().parent.parent / "data" / "kits" \
        / "rk909"
    capture = CaptureMidiIO()
    sampler = Sampler(load_kit(kit_dir))
    engine, _midi = rig(default_project(),
                        midi=SynthMidiBridge(capture, sampler))
    play(engine)
    heard = []
    for _tick in range(PASS):
        engine.step()
        if _tick % 24 == 0:
            heard.append(sampler.render(256))
    assert float(np.sqrt(np.mean(np.square(np.concatenate(heard))))) > 0.001
    engine.submit(cmd.SetMasterField(name="reverb", value=0.8))
    engine.submit(base.Stop())
    engine.step()
    assert not capture.hanging()
    assert not sampler.hanging_voices()
    assert np.all(np.isfinite(sampler.render(256)))
