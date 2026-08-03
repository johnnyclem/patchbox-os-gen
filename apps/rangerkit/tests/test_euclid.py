"""Euclidean generator properties, checked exhaustively over the usable range."""
from __future__ import annotations

from rangerkit.euclid import euclidean, pulse_positions


def test_pulse_count_is_exact():
    for steps in range(1, 33):
        for pulses in range(0, steps + 1):
            assert sum(euclidean(steps, pulses)) == pulses


def test_length_is_steps():
    for steps in range(1, 33):
        assert len(euclidean(steps, 5)) == steps


def test_even_distribution():
    """No gap between consecutive pulses differs from another by more than
    one step — the defining property of a Euclidean rhythm."""
    for steps in range(2, 33):
        for pulses in range(1, steps + 1):
            positions = pulse_positions(euclidean(steps, pulses))
            gaps = [(positions[(i + 1) % len(positions)] - positions[i])
                    % steps for i in range(len(positions))]
            if len(positions) > 1:
                assert max(gaps) - min(gaps) <= 1, (steps, pulses, gaps)


def test_known_patterns():
    assert euclidean(8, 3) == (True, False, False, True, False, False,
                               True, False)
    assert euclidean(4, 4) == (True,) * 4
    assert euclidean(8, 0) == (False,) * 8


def test_rotation_shifts_left():
    base = euclidean(8, 3)
    rotated = euclidean(8, 3, rotate=3)
    assert rotated == base[3:] + base[:3]
    assert euclidean(8, 3, rotate=8) == base


def test_degenerate_inputs_do_not_raise():
    assert euclidean(0, 3) == ()
    assert euclidean(-4, 3) == ()
    assert euclidean(8, -1) == (False,) * 8
    assert sum(euclidean(8, 99)) == 8
