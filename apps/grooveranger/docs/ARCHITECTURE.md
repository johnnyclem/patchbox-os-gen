# GrooveRanger architecture

**Scope:** a sample groovebox on Raspberry Pi 5 + Pimidi/Pisound + a
1280×400 touch bar, sharing an image with the other Ranger apps and
`rangerkit` with its siblings. Family-wide rules live in
[rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md); this file
is what GrooveRanger adds.

## 1. Patterns compile; the tick loop looks itself up

A ``Pattern`` is immutable material (twelve rows × sixteen ``Step``s).
``build_schedule`` compiles it — with swing and micro-timing already
leaned, ratchets already unrolled — into a dict from pattern-local tick to
due hits. Edits recompile (cheap, on the command path); the tick loop only
does a dict lookup. Probability and trig conditions are deliberately *not*
compiled: they are resolved at fire time from the pass counter, the fill
flag and the project's seeded rng, so twin engines from one project emit
identical streams — the family's determinism headline, drums edition.

## 2. Everything lands at pass end

Pattern switches queue, fills queue, the song chain presses pattern
buttons — all of it resolves at the pattern's own bar line
(``Sequencer.on_pass_end``). One boundary means one rule to test and no
race between a song step and a hand on the pattern row. Song mode is
*only* a scheduled hand: everything true of live switching is true in a
song.

## 3. The internal endpoint speaks per-pad channels

External destination: a pad is (kit channel, pad note), classic drum-box.
Internal destination: **channel = pad index**, and that one decision buys
the whole audio feature set as plain MIDI:

- parameter locks are CC 16 (tune) / 74 (filter) / 10 (pan) emitted
  immediately before the hit, consumed by the sampler's next note-on on
  that channel;
- mixer levels are CC 7 per pad channel; channel 15 is the master bus
  (74 filter, 85 delay division, 91 reverb, 7 level);
- chokes and mutes are the release book doing what it always does.

The engine never holds the sampler. Every fact the sampler needs either
travels as MIDI through the shared ``SynthMidiBridge`` (which forwards
CCs to any instrument exposing ``control``) or is a kit swap the App does
on its own thread when the snapshot's ``kit_rev`` moves. On a shared
external channel the per-hit CCs are suppressed — they would bend every
other pad on it.

## 4. Drums are one-shots; the ledger is still exact

A sampler note-off does not cut the sample — it marks the voice released
in ``hanging_voices()`` (the audio spelling of ``midi.hanging()``) and
lets it ring out. A choke (same choke group firing) cuts in 5 ms. Because
the engine books an off for every hit, the ledger drains without special
cases, and the engine runs ``FREE_RUN`` so auditioned pads release with
the transport stopped.

## 5. The DSP has no per-sample Python

Voice pitch is a linear-interp read; the per-pad tone filter is a Hann FIR
applied once at trigger and cached per (sample, cutoff step); the master
one-knob filter is a block FIR with carried tail; delay and every reverb
stage keep loop times longer than one 256-frame block, so feedback only
reads earlier blocks and everything vectorizes. 48 kHz float32 internal —
the honesty contract from suite Phase 4 — and the whole bus is documented
lo-fi (undamped combs, hard delay retune) rather than accidentally so.

## 6. What the tests assert

- Schedules place hits (swing leans odd 16ths, micro wraps, ratchets
  subdivide); conditions and one-pass fills gate at the right passes;
  probability is deterministic across twin engines.
- Emission: internal pads on their own channels, lock CCs before the hit,
  external kit-channel emission with lock CCs suppressed.
- Mutes/solos/mute groups silence *and release mid-note*; pattern
  switches queue; the chain alternates entries; recording quantizes into
  the pattern; every engine test ends ``assert not midi.hanging()``.
- Sampler: WAV decode + resample, velocity layers pick different files,
  chokes cut, locks consumed once, level CCs scale, stealing bounds
  voices, renders are deterministic and finite; ``hanging_voices()``
  empties exactly when the release book drains — proven end to end
  through the real bridge.
- Panel: every drawn control is a registered hit target, and pressing
  every control at 1280×400, 800×480 and 480×800 leaves nothing hanging.

## Deferred (deliberately)

Sidechain compression on the bus, sample recording/resampling, per-step
pad polyphony (a step is one hit), damped reverb (needs per-sample state),
and kit editing beyond continuous params — kits are files.
