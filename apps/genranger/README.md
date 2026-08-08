# GenRanger

*"You set the rules. It evolves."*

The generative sequencer of the Ranger suite: up to six layers (rhythm,
bass, melody, harmony, drone, CC) each driven by one of five algorithms —
Euclidean, order-N Markov over scale degrees, probability grids, 1-D
cellular automata, constrained random — with **Cruise** slowly mutating the
piece, lock regions holding what works, seed slots capturing whole states,
and a 32-entry timeline so "do the thing you did two minutes ago" is a
button. Same Pi 5 + 1280×400 touch bar rig as its siblings.

Inspirations: Marbles · Ornament & Crime · Orca · Eno's generative systems.

**Deterministic by contract:** the same project produces the same MIDI,
byte for byte, on any box, forever. All randomness flows from seeded
generators; mutation changes *(params, seed)*, never notes. The headline
test builds two engines from one project and asserts identical event
streams over eight bars.

![GenRanger PERFORM — Cruise, the chaos/density/complexity trio, six layers](docs/img/panel-1280x400-0-perform.png)

## Running it

```bash
python main.py                    # 1280x400 window, playing immediately
python main.py --size 480x800     # the portrait panel
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/genranger/config.toml    # the appliance
```

The factory project sounds the moment it boots: a Euclidean kick lattice,
a Markov walking bass, a sparse grid melody and long random pads in C minor,
with Cruise on. The engine core is stdlib + the vendored
[rangerkit](../rangerkit) only; MIDI degrades to a null backend when
mido/python-rtmidi are absent.

## The shape

- `core/` — `layers` (Pattern/LayerParams/generator table), one module per
  algorithm, `mutate` (the op vocabulary), `cruise` (round-robin, bar-line
  firings), `seeds` (splitmix hash + 8 slots), `timeline` (32-state ring,
  walkable both ways), `macros` (density/complexity as a render-time lens),
  `engine`. No pygame at import; every engine test ends
  `assert not midi.hanging()`.
- `gui/` — **PERFORM** (cruise/mutate/lock-all, macros, layer strips),
  **MAP** (probability lattice, CA seed row + rule, per-algorithm editors,
  the lock-range strip), **LAYERS** (identity/register/state + the key),
  **SEEDS** (8 pads + the timeline), **SET**.

## The Button

1 click play/stop · 2 clicks mutate now · 3 clicks lock-all ·
hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

Evolution speed and chaos by default (`[pots.map]`; density/complexity also
available). MIDI CC learn on the SET screen.

## Tests

```bash
python -m pytest -q           # headless: SDL dummy + capture MIDI + fake clock
python bench/render_panel.py /tmp/panel --size 1280x400   # screenshots
```
