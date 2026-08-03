# PhraseRanger architecture

**Scope:** an eight-track MIDI phrase looper on Raspberry Pi 5 +
Pimidi/Pisound + a 1280×400 touch bar, sharing an image with the other
Ranger apps and `rangerkit` with its siblings. Family-wide rules live in
[rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md); this file is
what PhraseRanger adds.

## 1. Phrases are values

Every looper verb — overdub, undo, reverse, stretch, decay, slice, fold —
is a pure function from one immutable ``Phrase`` to another. That one
decision *is* the feature list: multi-level undo is a stack of old phrases
(``core/history.py``, sixteen deep per track), scenes are dicts of phrases,
the slicer's pads are ``window``/``transposed`` views computed on demand,
and no operation can corrupt what is sounding because nothing is edited in
place. A phrase stores no channel: routing belongs to the track, so
material moved between tracks follows its new home's plumbing.

## 2. Take boundaries

The recorder is armed at exactly one track (a looper pedal has one input
path). The undo point is pushed at *arm* time — the pre-take phrase — so
"undo the last overdub" is a pop, whatever happened during the take.
Disarm (tap the armed track's ARM, or panic, or a scene recall) lands the
take: open notes are closed at that instant, because a take must never
hold a note the player let go of. The same closing happens on stop.

Feedback below unity is applied per loop wrap *while a take is open and has
added notes* — each pass multiplies the old material's velocities, and
whispers below the floor die. That is tape generations, note-domain.

## 3. Two live paths

* **Monitor thru** — an input note sounds on the armed track's output
  immediately (booked with the family's 16-bar safety length, released on
  the player's note-off), so the player hears the take as it goes down,
  transport running or not.
* **Slice pads** — a pad fires its window of the source phrase *now*, from
  the schedule heap. Both paths are why the engine is FREE_RUN: pads and
  monitoring must work with the transport stopped. Loop *playback* is
  transport-bound.

## 4. Feel is applied at emit, never written

Probability, humanize (delay-only) and velocity jitter shape the copy being
emitted, from the project's seeded rng; the phrase is untouched. Turning
density down and back up returns exactly the take — the same lens rule the
family's macros follow.

## 5. Loop lengths and polyrhythm

A track is either locked to the global bar count or free with its own.
Length changes *fold* out-of-range notes (position modulo the new length)
rather than deleting them — a loop halved keeps its material. Free-length
tracks phase against locked ones; that is the polyrhythm feature, priced at
one boolean.

## 6. What the tests assert

- Record lands in the armed track and replays every pass; quantize snaps
  takes; save/load round-trips them byte-for-byte.
- Undo peels takes in order down to empty and releases what was sounding;
  clear/reverse/stretch are undoable.
- Feedback decays old material only while overdubbing; unity feedback
  keeps layers forever.
- Probability silences playback without touching material; humanize only
  delays; rerouting mid-note releases the old plumbing.
- Slice pads fire with the transport stopped; chromatic pads transpose;
  soft layers scale; empty pads are no-ops.
- Scenes restore complete track states with nothing left hanging.
- Panel: every drawn control is a registered hit target, and pressing every
  control at 1280×400, 800×480 and 480×800 leaves nothing hanging.

## Deferred (deliberately)

Theory-aware cruise suggestions, per-note piano-roll editing (out of scope
by PRD), audio warping (ditto). (DAC preview shipped with suite Phase 4:
point a track's ``dest`` at ``internal`` and the soft-triangle synth answers
on the DAC.)
