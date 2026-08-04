# SynthRanger

*"Four engines, four parts, one knob between two sounds."*

The polysynth of the Ranger suite: a multitimbral soft synth purpose-built
for the 1280×400 bar — four oscillator engines (band-limited virtual
analog, 2-op FM, wavetable scan, CZ-style phase distortion), a two-pole
filter with cutoff-tracking emphasis, dual ADSRs, an LFO, a four-slot mod
matrix fed by an on-screen XY pad, patch morphing (A ↔ B on one knob),
per-part drive + chorus with a shared tempo-synced delay, and a preset
bank. Same Pi 5 + touch bar rig as its siblings.

Inspirations: microKORG · Casio CZ · DX7 · Blofeld.

## The floor, documented honestly

Internal render is **48 kHz float32, 256-frame blocks** (the Pisound DAC
path may clock higher; the synthesis does not pretend to it). The
performance floor is **8 voices per part, 4 parts** — CI enforces a canary
(8 sounding voices render 1 s of audio in < 2 s of CPU) so a DSP
regression fails a build instead of gliching a gig. Nothing in the DSP
loops over samples in Python: oscillators are mip-mapped table reads, the
filter is a closed-form one-pole cascade, envelopes are per-segment
closed forms, and every effect loop is longer than one block.

## Running it

```bash
python main.py                    # 1280x400 window
python main.py --size 480x800     # the portrait panel
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/synthranger/config.toml    # the appliance
```

MIDI degrades to a null backend without mido/python-rtmidi, audio to a
silent null device without sounddevice — CI runs both degradations on
every push.

## The shape

- `core/dsp/` — numpy, headless-importable: `tables` (band-limited,
  mip-mapped), `oscillators` (va/fm/wavetable/pd, all pure functions of a
  phase ramp), `filters` (vectorized one-pole cascade; resonance is a
  stable band emphasis, a documented color), `effects` (drive, chorus,
  delay).
- `core/` — `voices` (the Synth: allocator, `hanging_voices()`, per-part
  render), `parts`/`patch` (immutable values), `morph` (numeric lerp,
  categorical snap, never writes back), `modmatrix` (4 slots: XY / wheel /
  velocity / LFO → cutoff / pitch / timbre / …), `envelope`, `lfo`,
  `preset`, `fxchain`, `engine`. No pygame at import; every engine test
  ends with nothing hanging — MIDI bookings *or* voices.
- `gui/` — **PERFORM** (two-octave touch keyboard + XY pad + morph),
  **EDIT** (the whole patch), **BROWSER** (factory + user presets),
  **MIX** (part strips + the mod matrix), **SET** (ports, clock, pots,
  project, theme).
- `data/presets/` — eight factory patches covering all four engines.

## The internal contract

Notes route by part listen channel through the engine's release book onto
the ``internal`` endpoint (channel = part index) — stop, panic and mutes
release synth voices exactly as they release external gear. CC 1 is the
mod wheel, CC 74 a cutoff offset, CC 16/17 the XY pad, channel 15 CC 7
the master level. Patches never travel as MIDI: the App swaps the
immutable parts tuple when the snapshot's ``parts_rev`` moves.

## The Button

1 click clock run/stop · 2 clicks next part · 3 clicks all notes off ·
hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

Cutoff and morph on the selected part by default (`[pots.map]`). MIDI CC
learn on the SET screen.

## Tests

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q
```

DSP correctness (the one-pole matches its recurrence; engines are
deterministic and finite), voice lifecycle and stealing, morph and matrix
semantics, preset round-trips, engine routing through the real bridge,
press-everything GUI tests at 1280×400, 800×480 and 480×800, and the
perf canary.
