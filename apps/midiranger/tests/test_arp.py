"""The arpeggiator, stepped by hand with a seeded Random."""
from __future__ import annotations

import random

from core.arp import ANY_SOURCE, Arp, ArpParams, OMNI
from rangerkit.events import PPQN

RATE = PPQN // 4


def rng():
    return random.Random(1)


def held_arp(pattern="up", **kwargs) -> Arp:
    arp = Arp(ArpParams(enabled=True, pattern=pattern, rate=RATE, **kwargs))
    arp.note_on(60, 100)
    arp.note_on(64, 90)
    arp.note_on(67, 80)
    return arp


def steps(arp: Arp, count: int, r=None) -> list:
    """The notes of ``count`` consecutive steps (offset-0 hits only)."""
    r = r or rng()
    out = []
    for tick in range(0, count * RATE):
        for offset, note, _velocity, _length in arp.on_tick(tick, r):
            if offset == 0:
                out.append(note)
    return out


def test_matches_filters_endpoint_and_channel():
    arp = Arp(ArpParams(enabled=True, source="din_in", channel_in=3))
    assert arp.matches("din_in", 3)
    assert not arp.matches("din_in", 4)
    assert not arp.matches("usb_in", 3)
    omni = Arp(ArpParams(enabled=True, source=ANY_SOURCE, channel_in=OMNI))
    assert omni.matches("din_in", 0) and omni.matches("usb_in", 15)
    assert not Arp(ArpParams(enabled=False)).matches("din_in", 0)


def test_up_down_updown_order():
    assert steps(held_arp("up"), 6) == [60, 64, 67, 60, 64, 67]
    assert steps(held_arp("down"), 6) == [67, 64, 60, 67, 64, 60]
    assert steps(held_arp("updown"), 8) == [60, 64, 67, 64, 60, 64, 67, 64]
    ordered = held_arp("order")
    assert steps(ordered, 3) == [60, 64, 67]        # press order


def test_octaves_stack_upward():
    arp = held_arp("up", octaves=2)
    assert steps(arp, 6) == [60, 64, 67, 72, 76, 79]


def test_nothing_between_steps_or_when_empty():
    arp = held_arp("up")
    r = rng()
    assert arp.on_tick(1, r) == []
    empty = Arp(ArpParams(enabled=True))
    assert empty.on_tick(0, r) == []


def test_gate_sets_length_and_ratchet_subdivides():
    arp = held_arp("up", gate=0.5)
    hits = arp.on_tick(0, rng())
    assert hits == [(0, 60, 100, RATE // 2)]
    ratchet = held_arp("up", ratchet=3, gate=1.0)
    hits = ratchet.on_tick(0, rng())
    span = RATE // 3
    assert [(o, n) for o, n, _v, _l in hits] == \
        [(0, 60), (span, 60), (span * 2, 60)]
    assert all(length == span for _o, _n, _v, length in hits)


def test_probability_skips_but_advances():
    arp = held_arp("up", probability=0.0)
    assert steps(arp, 4) == []
    # The step counter still moved: back at probability 1, the pattern
    # resumes mid-cycle instead of restarting from the first note.
    assert arp._step == 4


def test_note_off_removes_and_resets_when_empty():
    arp = held_arp("up")
    arp.note_off(64)
    assert steps(arp, 2) == [60, 67]
    arp.note_off(60)
    arp.note_off(67)
    assert arp.on_tick(0, rng()) == []
    assert arp._step == 0


def test_hold_latches_until_a_new_phrase():
    arp = held_arp("up", hold=True)
    arp.note_off(60)
    arp.note_off(64)
    arp.note_off(67)
    assert arp.held_notes() == (60, 64, 67)         # latched
    arp.note_on(48, 100)                            # new phrase: old yields
    assert arp.held_notes() == (48,)


def test_dropping_hold_keeps_only_physical_keys():
    arp = held_arp("up", hold=True)
    arp.note_off(64)
    arp.set_params(arp.params.__class__(
        **{**_params_dict(arp.params), "hold": False}))
    assert sorted(arp.held_notes()) == [60, 67]


def test_random_pattern_is_seeded():
    a = steps(held_arp("random"), 8, random.Random(42))
    b = steps(held_arp("random"), 8, random.Random(42))
    assert a == b
    assert set(a) <= {60, 64, 67}


def _params_dict(params) -> dict:
    from dataclasses import asdict
    return asdict(params)
