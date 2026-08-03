"""The pure sequencer layer: steps, schedules, switching, song mode.

No engine, no MIDI, no numpy — this is the material and the compiler, the
part of the groovebox that must be right before anything makes sound.
"""
from __future__ import annotations

from core.phrasechain import Chain
from core.sequencer import (PATTERNS, STEP_TICKS, Sequencer, build_schedule,
                            swing_ticks)
from core.steps import (CONDITIONS, PADS, Pattern, STEPS, Step, cond_passes)


# --- steps ---------------------------------------------------------------------

def test_step_normalises_and_locks():
    step = Step(on=True, vel=200, prob=2.0, ratchet=9, cond="bogus",
                micro=99).normalised()
    assert (step.vel, step.prob, step.ratchet, step.cond, step.micro) \
        == (127, 1.0, 4, "always", 11)
    locked = step.lock("tune", 5.0).lock("pan", -0.5)
    assert locked.locked("tune") == 5.0 and locked.locked("pan") == -0.5
    assert locked.lock("tune", None).locked("tune") is None
    assert step.lock("bogus", 1.0).plocks == ()


def test_conditions():
    assert cond_passes("always", 0, False)
    assert cond_passes("fill", 3, True) and not cond_passes("fill", 3, False)
    assert cond_passes("not_fill", 0, False)
    assert [cond_passes("1:2", n, False) for n in range(4)] \
        == [True, False, True, False]
    assert [cond_passes("3:4", n, False) for n in range(8)] \
        == [False, False, True, False] * 2
    for cond in CONDITIONS:
        cond_passes(cond, 5, True)      # nothing raises


def test_pattern_edits_are_immutable():
    a = Pattern()
    b = a.toggle(0, 0)
    assert not a.step(0, 0).on and b.step(0, 0).on
    assert b.toggle(0, 0).step(0, 0).on is False
    assert b.clear_row(0).used() == 0
    assert Pattern.from_config(b.to_config()) == b


def test_euclid_row_places_pulses():
    pattern = Pattern().euclid_row(3, 4)
    row = pattern.rows[3]
    assert [i for i in range(STEPS) if row[i].on] == [0, 4, 8, 12]
    assert Pattern(length=12).euclid_row(0, 12).used() == 12


# --- the schedule --------------------------------------------------------------

def test_schedule_places_hits_and_swing_leans_the_offbeats():
    pattern = Pattern().toggle(0, 0).toggle(0, 1)
    straight = build_schedule(pattern, 0.5)
    assert 0 in straight and STEP_TICKS in straight
    swung = build_schedule(pattern, 0.75)
    assert swing_ticks(0.75) == STEP_TICKS // 2
    assert STEP_TICKS + STEP_TICKS // 2 in swung
    assert STEP_TICKS not in swung


def test_micro_timing_and_ratchets():
    pattern = Pattern()
    step = Step(on=True, micro=-3, ratchet=3).normalised()
    pattern = pattern.with_step(2, 4, step)
    schedule = build_schedule(pattern, 0.5)
    base = 4 * STEP_TICKS - 3
    hits = sorted(t for t, hs in schedule.items()
                  for h in hs if h.pad == 2)
    assert hits == [base, base + 8, base + 16]
    assert all(h.ratchet_of == 3 for hs in schedule.values() for h in hs)


def test_negative_micro_on_step_zero_wraps_to_pattern_end():
    pattern = Pattern().with_step(0, 0, Step(on=True, micro=-2))
    schedule = build_schedule(pattern, 0.5)
    assert 16 * STEP_TICKS - 2 in schedule


# --- the runtime ---------------------------------------------------------------

def test_pattern_switch_lands_at_pass_end():
    seq = Sequencer()
    seq.queue_pattern(3)
    assert seq.current == 0 and seq.queued == 3
    seq.on_pass_end()
    assert seq.current == 3 and seq.queued is None and seq.loop == 0


def test_fill_is_one_pass_long():
    seq = Sequencer()
    seq.queue_fill()
    assert not seq.fill and seq.fill_queued
    seq.on_pass_end()
    assert seq.fill and not seq.fill_queued
    seq.on_pass_end()
    assert not seq.fill


def test_solo_beats_mute():
    seq = Sequencer()
    seq.mutes.add(2)
    assert not seq.audible(2) and seq.audible(0)
    seq.solos.add(2)
    assert seq.audible(2) and not seq.audible(0)


def test_record_hit_quantizes_to_nearest_step():
    seq = Sequencer()
    seq.record_hit(STEP_TICKS + 13, 5, 99)          # late, rounds to step 2
    seq.record_hit(seq.pattern().length * STEP_TICKS - 5, 6, 80)  # wraps
    assert seq.pattern().step(5, 2).on
    assert seq.pattern().step(5, 2).vel == 99
    assert seq.pattern().step(6, 0).on


def test_sequencer_round_trips_through_config():
    seq = Sequencer()
    seq.edit(seq.pattern().toggle(0, 0).euclid_row(4, 5))
    seq.set_swing(0.62)
    seq.mutes.add(7)
    seq.queue_pattern(2)
    other = Sequencer()
    other.from_config(seq.to_config())
    assert other.patterns == seq.patterns
    assert other.swing == seq.swing and other.mutes == {7}
    assert other.queued is None                     # transport state resets


def test_schedule_cache_invalidates_on_edit():
    seq = Sequencer()
    assert seq.hits_at(0) == ()
    seq.edit(seq.pattern().toggle(0, 0))
    assert len(seq.hits_at(0)) == 1
    seq.set_swing(0.7)
    assert len(seq.hits_at(0)) == 1


# --- song mode -----------------------------------------------------------------

def test_chain_walks_entries_and_loops():
    chain = Chain()
    chain.append(0, 2)
    chain.append(5, 1)
    assert chain.start() == 0
    assert chain.on_pass_end() is None              # pass 1 of 2
    assert chain.on_pass_end() == 5
    assert chain.on_pass_end() == 0                 # looped
    chain.stop()
    assert chain.on_pass_end() is None


def test_chain_survives_config_but_stays_off():
    chain = Chain()
    chain.append(1, 4)
    chain.on = True
    restored = Chain.from_config(chain.to_config())
    assert restored.entries == [(1, 4)]
    assert not restored.on


def test_chain_remove_clamps_position():
    chain = Chain()
    for pattern in range(3):
        chain.append(pattern, 1)
    chain.start()
    chain.on_pass_end()
    chain.on_pass_end()
    assert chain.position == 2
    chain.remove(2)
    assert chain.position <= 1
    chain.remove(9)                                 # out of range: no-op
    assert len(chain.entries) == 2


def test_patterns_index_bounds():
    seq = Sequencer()
    seq.queue_pattern(PATTERNS)                     # out of range
    assert seq.queued is None
    seq.switch_now(-1)
    assert seq.current == 0
    assert all(not seq.audible(p) or p < PADS for p in range(PADS))
