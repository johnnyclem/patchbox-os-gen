# SynthRanger architecture

**Scope:** a four-part multi-engine polysynth on Raspberry Pi 5 +
Pimidi/Pisound + a 1280×400 touch bar, sharing an image with the other
Ranger apps and `rangerkit` with its siblings. Family-wide rules live in
[rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md); this file
is what SynthRanger adds.

## 1. The engine is a router; the instrument is a value consumer

The `RangerEngine` subclass owns *state*: the immutable parts tuple, note
routing, the project tree. The `Synth` (behind the shared
`SynthMidiBridge`) owns *sound*. They never hold each other. Everything
crossing between them is either MIDI on the `internal` endpoint (notes
booked through the release book, channel = part index; CC 1/74/16/17 for
wheel, cutoff, XY) or an immutable tuple swap the App performs when the
snapshot's `parts_rev` moves. Stop, panic and part mutes therefore
release voices through exactly the machinery that releases external gear
— `hanging_voices()` mirrors `midi.hanging()` and the tests assert both.

## 2. Everything musical is a value

A `Patch` is a frozen dataclass of numbers; a `Part` is two patches, a
morph position, a matrix and a mix strip. Presets store a patch, projects
store parts, morphing interpolates patches (numeric fields lerp,
categorical snap at the midpoint) and *never writes back* — the family's
lens rule. A sounding voice reads its part's effective patch fresh every
block, so edits and morphs land on held notes without a single lock.

## 3. No per-sample Python, and where that shows

* Oscillators are pure functions of a phase ramp over mip-mapped
  band-limited tables (VA, wavetable scan, PD's bent-ramp cosine) or two
  sine reads (FM, no feedback op).
* The filter is two one-pole low-passes computed in closed form
  (cumulative-sum for smooth poles, short FIR for fast ones).
  **Resonance is a cutoff-tracking band emphasis** (stage-1 − stage-2,
  scaled) — stable by construction at every setting, fully parallel, and
  a documented color rather than a ladder imitation.
* Envelopes render per segment in closed form; the LFO is control-rate
  (one value per 256-frame block); chorus reads an input history (no
  feedback, so its tap may sit inside a block) and the delay's loop is
  clamped longer than a block.

The CI perf canary (8 voices × 1 s in < 2 s CPU) turns this discipline
into a failing test instead of a stage problem.

## 4. The mod matrix is the performance surface

Four slots per part: source (XY pad, mod wheel, velocity, LFO) →
destination (cutoff, pitch, timbre, resonance, drive) × amount, resolved
once per block into offsets on the effective patch. `timbre` is one
deliberate indirection: it lands on whichever parameter gives the current
engine its character (detune / FM index / wavetable position / PD warp),
so the XY pad stays meaningful when the engine changes under it.

## 5. What the tests assert

- The one-pole matches its textbook recurrence and carries state across
  blocks; every engine renders finite, deterministic audio; FM index and
  PD warp add harmonics; the wavetable scan actually moves.
- Voice lifecycle: silence → note → release tail → silence; the per-part
  poly cap steals the oldest; parts are isolated; edits land under sound.
- Morph endpoints are exact and A is untouched; the matrix audibly
  reaches the filter; presets and projects round-trip byte-faithful.
- Routing: listen channels, muted parts deaf *and* released, channel
  reassignment releases old plumbing — all through the real bridge, and
  every test ends with nothing hanging, bookings or voices.
- Panel: every drawn control is a registered hit target, and pressing
  every control at 1280×400, 800×480 and 480×800 leaves nothing hanging.
- The perf canary above.

## Deferred (deliberately)

The PRD's 16-voice × 8-part stretch (needs a C extension; the floor is
documented instead), oscillator sync/ring/noise, a feedback ladder
filter, per-voice glide, MPE, and effects beyond drive/chorus/delay.
