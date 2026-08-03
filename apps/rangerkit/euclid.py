"""Euclidean rhythm generation (Bjorklund's algorithm).

Used by GrooveRanger's generators, GenRanger's rhythm layers and MidiRanger's
arp patterns — one implementation, property-tested once.

A pattern is a tuple of booleans, one per step, ``True`` where a pulse lands.
The defining property: the pulses are as evenly spread as integer arithmetic
allows, which is why E(3,8) is the tresillo and E(5,8) is the cinquillo.
"""
from __future__ import annotations


def euclidean(steps: int, pulses: int, rotate: int = 0) -> tuple[bool, ...]:
    """E(pulses, steps) rotated left by ``rotate`` steps.

    Degenerate inputs answer sensibly rather than raising: zero (or negative)
    steps is the empty pattern, zero pulses is all rests, and pulses beyond
    steps saturates to all hits — a panel knob swept past its useful range
    should pin, not crash.
    """
    if steps <= 0:
        return ()
    pulses = max(0, min(int(pulses), steps))
    if pulses == 0:
        return (False,) * steps
    # Bresenham formulation of Bjorklund: a pulse lands wherever the running
    # error accumulator wraps. Equivalent output, far less bookkeeping.
    pattern = []
    previous = -1
    for index in range(steps):
        level = (index * pulses) // steps
        pattern.append(level != previous)
        previous = level
    if rotate:
        offset = rotate % steps
        pattern = pattern[offset:] + pattern[:offset]
    return tuple(pattern)


def pulse_positions(pattern: tuple[bool, ...]) -> tuple[int, ...]:
    """Indices of the hits — what a sequencer actually schedules."""
    return tuple(index for index, hit in enumerate(pattern) if hit)
