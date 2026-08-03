# ChordRanger architecture

**Scope:** a chord-first backing band on Raspberry Pi 5 + Pisound + a 1280×400
touch bar, sharing an image with RK-00pi and sharing none of its code.

---

## 1. The shape

One process, three layers, one hard rule: **the engine owns every note it has
sent.**

```
   touch / MIDI-in / button
              │  Command values
              ▼
   ┌─────────────────────────┐
   │  engine (RT thread)     │   drain commands
   │   song → chord          │   apply the chord track
   │   arranger → notes      │   render the bar, emit this tick's notes
   │   release book          │   send the note-offs that came due
   └─────────────────────────┘
              │  EngineSnapshot (immutable, once per frame)
              ▼
        gui (pygame, 60 fps)
```

Commands in, snapshots out. The GUI never touches engine state, which means
the engine needs no locks and the panel can die — crash, be closed, be run
under a test harness that never draws a pixel — without stopping the music.
`--headless` is a supported way to run the instrument for exactly that reason.

### Why the release book matters

Every note-on is booked into `Engine._release` with its off-tick at the moment
it goes out. A chord change, a section switch, a style swap, a mute, a locate
and a panic all work by consulting that book. Nothing else may emit a note-on.

This is the single design decision the rest of the engine is arranged around,
because the failure it prevents — a MIDI instrument holding a note forever —
is indistinguishable on a stage from a broken instrument, and it is invisible
in a test that only checks what was played.

Every engine test therefore ends with `assert not midi.hanging()`.

---

## 2. Two number spaces

| Space | Range | Who uses it |
|-------|-------|-------------|
| pitch class | 0–11, C = 0 | chords, scales, keys — "C major" is the same idea in every register |
| MIDI note | 0–127, 60 = middle C | the voicing layer and the engine, and nothing above them |

Mixing them is the classic bug in this kind of code. `core.theory.pc()` is the
one-way door.

---

## 3. Chord, voicing, and the dial

A `Chord` is a harmonic *idea*: root, quality, an optional slash bass, and —
for a hand-edited chord — an explicit interval set. It has no register.

Turning one into notes is `core.chords.voice()`, and the split is deliberate:
the same C-7 is voiced one way for the chord part (mid register, drop-2) and
another for the bass (one note, two octaves down), and neither may mutate the
other's idea of the chord.

`walk(notes, steps)` is the Orchid voicing dial. One positive step lifts the
lowest note an octave; one negative step drops the highest. **The pitch-class
set is invariant along the whole travel** — it is voice leading, not
re-harmonisation, which is what makes it safe to bind to a control a player
turns while a chord is sounding.

A slash chord is *not* an inversion. `C/E` names its bass note; a
first-inversion C merely happens to have E lowest. Conflating them would make
the two indistinguishable, and only one of them constrains the bass engine.

---

## 4. The style model

A **style** is a band: five parts (drums, bass, chord, keys, lead) and, for
each of six **sections**, one phrase per part.

```
INTRO ─▶ MAIN A ──FILL AB──▶ MAIN B ──FILL BA──▶ MAIN A ─▶ ENDING
```

Six sections rather than "as many patterns as you like", because it is a shape
a player can drive with two buttons while both hands are busy. Section lengths
follow the QY convention: intro 2, main A 2, fills 1, main B 4, ending 2.

A **phrase** is written once, in C, and bent onto the current chord. The
bending rule is per part:

| Rule | What it does | Who uses it |
|------|--------------|-------------|
| `fixed` | nothing at all | drums |
| `root` | every note becomes the chord's bass note | simple bass |
| `chord_tone` | snap to the nearest tone of the chord | comping |
| `scale` | transpose, then snap into the key's scale | melodic lines |
| `parallel` | transpose by the root delta, unaltered | riffs, power-chord stabs |

`parallel` is the honest name for what a guitarist does: move the shape and
let the harmony take care of itself. It sounds wrong over anything that is not
a plain triad — which is precisely when a style author should pick another
rule, so the rule is stored per phrase and can be overridden per part.

All rules except `fixed` take the *short way round* the pitch-class circle: a
phrase in C played over B drops a semitone rather than climbing eleven and
taking the whole line with it.

---

## 5. The arranger

Two responsibilities the rest of the app deliberately does not have.

**Where we are in the form.** A state machine, not a song list, because a
player switching sections with one finger mid-performance is the primary use
and a written arrangement is the secondary one. A request to move between the
two mains routes through the matching fill automatically — making the player
press the fill themselves is how you get a fill that arrives one bar late,
every time.

**How a bar sounds over a chord.** Each bar is rendered when it begins: the
style's phrases are bent onto the chord, the chord part's rhythm is expanded
into a voicing, and the bass engine is asked for its own line. If the chord
changes *inside* the bar, the remainder is re-rendered on the spot — a band
does not finish the bar in the old key out of politeness — and only ticks at
or after the current position are kept, so nothing double-triggers.

Rendering per bar rather than per tick is what keeps the tick loop cheap: at
96 PPQN a bar is 384 ticks, and 383 of them are a dictionary lookup that
usually misses.

---

## 6. The bass as its own voice

A bass part that is merely "the lowest note of the chord voicing" cannot play
a passing tone, cannot anticipate the next chord, and cannot be silenced
without thinning the chord. So the bass takes the chord as *input*, not as
material: it knows the current chord, the next chord, the beat, and its own
pattern, and decides one note at a time.

The walk mode is the one that uses the lookahead. Its last hit of the bar is a
leading tone into the next chord's bass note — a scale step where there is
one, chromatic otherwise. That single note is what makes a walking line sound
like it is going somewhere; without it the line is an arpeggio that stops.

---

## 7. The song is only chords

No notes are stored in a song — only chord changes positioned in bars and
beats, plus section markers. Everything you hear is generated from those and
the style.

Two consequences, both intended: a four-minute arrangement is a few hundred
bytes, and changing the style re-arranges the whole song rather than replacing
half of it.

---

## 8. Timing

PPQN 96. `RealClock` sleeps toward absolute deadlines, so a late wake-up is
repaid by the next tick arriving early rather than by the whole song drifting;
a missed deadline is left in the past and the engine runs catch-up ticks back
to back. Music that stutters once recovers its position — music that drifts
never does.

`FakeClock` advances instantly, which is what makes the engine testable: a
test runs four bars of arranger output in microseconds and asserts on exact
ticks, through the same `step()` the real transport uses. There is no
simulation path.

Tempo is recomputed from BPM each tick rather than accumulated, so a long set
cannot slowly diverge from the drummer.

---

## 9. MIDI I/O

Three backends behind one protocol: mido/python-rtmidi (the ALSA sequencer),
a capture backend the tests assert on, and null.

Degrading to null is load-bearing. An appliance whose MIDI package failed to
install should boot, draw its panel, and *say* on the Settings screen that it
has no output — not refuse to start. A silent instrument you can diagnose
beats a black screen every time.

Sends are queued and written by a separate thread, because a wedged USB gadget
or a full ALSA pool blocks whoever calls into it, and the one caller that must
never block is the tick thread: a stall there does not drop one note, it bends
the tempo of everything that follows. Note-offs and CC 123 get through even
when the queue is over its cap — dropping a note-on loses a note, dropping a
note-off loses the instrument.

---

## 10. Sharing a panel with RK-00pi

Both apps render through SDL's KMS/DRM backend and there is one display, so
exactly one may run. This is enforced in three places rather than documented
in one:

- `chordranger.service` declares `Conflicts=rk00pi.service`;
- the install stage does not enable ChordRanger's unit unless
  `ENABLE_CHORDRANGER_SERVICE=1`, and disables RK-00pi's when it does;
- `patchbox-chordranger enable` / `disable` swaps them on a running unit,
  including the Pisound button map, and restores the previous map on the way
  back out.

RK-00pi and ChordRanger share no code. They share conventions — `/opt/<app>`,
`/var/lib/<app>`, `/etc/<app>/config.toml`, a button socket under `/run` — so
an operator who knows one knows the other.

The six newer Ranger apps (MidiRanger, GenRanger, PhraseRanger, SceneRanger,
GrooveRanger, SynthRanger) *do* share code: `apps/rangerkit`, whose theory,
clock, MIDI and engine skeleton were extracted from this app. ChordRanger
predates the kit and deliberately remains self-contained — it stays on its
own copies until a deliberate migration, so nothing here moves under a
shipped instrument's feet. The family-wide switcher `patchbox-app` also knows
this app; `patchbox-chordranger` keeps working unchanged.

---

## 11. What the tests actually assert

- **Harmony:** voicing never changes the pitch-class set; chord-tone
  conversion only ever produces chord tones; scale conversion stays in the
  key; a long progression stays in register.
- **Form:** the intro hands over to main A, a main loops, moving between mains
  routes through the right fill, the ending stops the transport, a style
  missing a section ignores the request rather than dying.
- **The engine:** nothing is ever left sounding — after a stop, a style swap,
  a locate, a song end, a panic, or two bars of every shipped style.
- **The panel:** every drawn control is a registered hit target, and pressing
  every registered control on every screen produces commands the engine
  accepts.
