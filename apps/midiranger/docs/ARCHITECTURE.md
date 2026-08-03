# MidiRanger architecture

**Scope:** a multi-port MIDI matrix and processing rack on Raspberry Pi 5 +
Pimidi/Pisound + a 1280×400 touch bar, sharing an image with the other
Ranger apps and sharing `rangerkit` with its five siblings.

The family-wide rules (release book, snapshots, headless cores, one panel /
one app) live in [rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md).
This file is only what MidiRanger adds.

## 1. Two time domains

The box does two jobs with different latency laws:

- **Thru** — a played note must reach its outputs *now*. The whole thru chain
  (quantize → harmonize → FX → matrix fan-out) runs when the input event is
  drained from the command queue, not on a tick boundary. The <5 ms in→out
  target is a queue-drain property; at 96 PPQN / 120 BPM a tick is ~5.2 ms,
  so waiting for one would already spend the budget.
- **Grid** — arps, ratchets, echoes and LFOs live on the tick grid, because
  their whole point is being in time.

The engine is `FREE_RUN`: its tick advances with the transport stopped, so
echoes and humanize delays still fire (a MIDI delay pedal has no transport).
`playing` gates only the musical clocks — arps, LFOs, MIDI clock out. The
appliance auto-plays at boot; the RUN button is a mute for motion, not a
power switch.

## 2. Who owns a note

Three producers, one law — every note-on goes through `send_note` and is
booked with an off-tick:

| Producer | Off strategy |
|----------|--------------|
| Thru notes | booked with a 16-bar safety length, released *early* when the player's note-off arrives (`_thru` maps input key → emitted keys) |
| Arp/ratchet/echo notes | booked with their real computed length |
| Everything on panic/stop/scene recall | the book is emptied + CC 123 |

The `_thru` map is also consulted when a route is removed mid-note: whatever
traveled the dead route is released at that moment, because its note-off no
longer has a path it is allowed to take.

CC, program and pitch-bend pass the matrix untouched and immediately — the
rack is a *note* rack, and a mod wheel that arrives late is worse than one
that arrives raw.

## 3. Consumption

An enabled arp whose input filter matches (endpoint + channel) *consumes*
matching notes: they feed the arp's held set instead of the thru path. This
is the Pyramid model — an arp is an instrument you play, not an effect
stacked on a stream — and it is what lets four arps driven from two
keyboards coexist with plain thru routing on a third port.

## 4. Determinism

One seeded `random.Random` (the project's seed) drives probability, random
patterns, humanize and drop. The S&H LFO derives its levels arithmetically
from (seed, step) rather than `hash()` (salted per process) or a shared rng
(order-dependent). Same project + same input + same ticks → the same
performance, which is what makes the engine tests exact rather than
statistical.

## 5. Scenes are parameter trees

`capture_params()` returns a JSON-able dict (routes, arps, quantizer,
harmonizer, FX, LFOs); scenes store copies, the project stores the same
shape, and morphing is a structural blend — numbers interpolate, everything
else switches at t=0.5, because half a route is not a thing. Recalling a
scene empties the release book first; a scene change that strands a note is
the exact bug the family exists to prevent.

## 6. What the tests assert

- Thru: immediate emission, fan-out with channel rewrite, release on player
  note-off, the 16-bar safety net, release on route removal.
- Rack: diatonic harmonization stays in scale; echoes decay and die below
  audibility; humanize only delays; drop is seeded.
- Arps: pattern order, octave stacking, gate/ratchet arithmetic, latch
  semantics, consumption vs thru, and a churn stress across bars ending —
  like every engine test — with `assert not midi.hanging()`.
- Scenes: save/recall round-trip, empty-slot recall is a message, recall
  mid-note strands nothing, morph blends numerics.
- Panel: every drawn control is a registered hit target, and pressing every
  registered control at 1280×400, 800×480 and 480×800 produces commands the
  engine accepts.
