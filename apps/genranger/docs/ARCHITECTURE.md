# GenRanger architecture

**Scope:** a generative multi-layer sequencer on Raspberry Pi 5 +
Pimidi/Pisound + a 1280×400 touch bar, sharing an image with the other
Ranger apps and `rangerkit` with its siblings. Family-wide rules live in
[rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md); this file is
what GenRanger adds.

## 1. Patterns, not decisions

A layer's music is an immutable rendered ``Pattern`` — a fixed grid of
steps. The tick loop only *reads*: at each step boundary it emits that
step's note through ``send_note`` (off-tick booked by the base release
book), which is why mute, stop, panic and scene restore mid-note are free.

A generator is a pure function ``render(params, rng, ctx, generation)``. At
each cycle boundary the layer's ``generation`` increments and the pattern
re-renders from ``Random(mix(seed, index, generation))`` — the stochastic
algorithms vary loop to loop, *deterministically*. Euclid ignores its rng
entirely and is the skeleton the rest evolves around.

## 2. Where randomness is allowed to come from

Three sources, strictly separated:

| rng | consumed by | seeded from |
|-----|-------------|-------------|
| pattern rng | generators, per render | ``mix(layer_seed, index, generation)`` |
| cruise rng | mutation ops, mutate-now target picks, reseeds | ``mix(project_seed, salt)`` |
| — | nothing else. ``hash()`` is banned (salted per process); the S&H arithmetic in ``seeds.mix`` replaces it. |

Same project + same command stream + same tick count ⇒ every rng is in the
same state ⇒ byte-identical MIDI. That is the headline test, and it is also
what makes the timeline honest.

## 3. Mutation is parameter surgery

Cruise fires on a bar-multiple interval (speed knob), mutates **one**
unlocked layer per firing (round-robin — starving nothing, churning
nothing), drawing ops from a weighted vocabulary (nudge density, rotate,
style/rule/temperature nudges, octave shift, velocity tilt, reseed) whose
boldness and count scale with chaos. Mutation never touches notes; it
changes *(params, seed)* and the next render does the rest.

Locks veto at two levels: a locked *layer's* params never change (vetoed in
``mutate``); a locked *step range* lets the mutation land and then copies
the previous pattern's steps back verbatim in ``render_layer``'s merge
stage — deterministic, so determinism survives locking.

## 4. The timeline and the seed slots speak one shape

``capture_state()`` returns a JSON-able dict: all six layers' params,
per-layer seeds and generations, the key, cruise and macros. Timeline
entries (32, coalesced to one per bar), the eight seed slots, and the
project file all store exactly this. Restore = release everything, apply,
re-render — you get back the very pattern that was sounding, and evolution
continues forward from it. Stepping the timeline never truncates it: the
player can walk both ways until new mutations overwrite the head.

## 5. Macros are a lens

Global density/complexity bias every layer's params *at render time* and
are never written back — turning a macro down and back up returns exactly
the piece you had.

## 6. What the tests assert

- **Determinism**: two engines from one project → identical event streams
  over 8 bars; the same across save/load.
- **Zero hanging notes** under stop, panic, mute (released *at the mute*),
  mutate-now storms, seed recall, timeline restore, key change and pot
  sweeps — every engine test ends ``assert not midi.hanging()``.
- **Generators**: patterns well-formed; euclid rng-free and
  density-monotone; markov in scale/register and mostly stepwise on "walk";
  Rule 90's XOR identity; grid extremes (all-0 silent, all-1 full);
  random's interval leash; the cc role renders curves, not notes.
- **Locks**: locked layers survive mutation storms; locked step ranges are
  copied verbatim while the rest changes.
- **Timeline/seeds**: restore returns the recorded state; the ring wraps at
  32; slots round-trip through the project file.
- **Panel**: every drawn control is a registered hit target, and pressing
  every control at 1280×400, 800×480 and 480×800 leaves nothing hanging.

## Deferred (deliberately)

Internal audio drones (suite Phase 4 — ``core/drones.py`` is the hook), the
MAP node-graph view, Markov learning from live input, order > 2, per-step
micro-timing.
