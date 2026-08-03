# SceneRanger architecture

**Scope:** an Ableton-style session clip launcher on Raspberry Pi 5 +
Pimidi/Pisound + a 1280×400 touch bar, sharing an image with the other
Ranger apps and `rangerkit` with its siblings. Family-wide rules live in
[rangerkit's CONVENTIONS](../../rangerkit/docs/CONVENTIONS.md); this file is
what SceneRanger adds.

## 1. Launches are queues; boundaries resolve them

A tap never plays a clip — it *queues* one on that track's launcher, and
the launch-quantize boundary resolves the queue ("off" makes every tick a
boundary, so the queue resolves on the next drain: the <5–10 ms
command-to-MIDI path is quantize-off by definition, not a special case).
Resolution releases the outgoing clip's channel through the release book
before the incoming clip's first note — legato by arithmetic, not luck.

## 2. A scene is a state, not a delta

Launching scene N queues every filled slot in row N *and queues a stop on
every track with nothing there*. Scene 4 therefore sounds like scene 4
regardless of what was playing — the property that makes scenes a
performance instrument rather than a bank of shortcuts.

## 3. Follow actions make the grid self-playing

Each clip carries (action, loop count, probability): when the active clip
completes its loops, the action queues the successor — again / next / prev
(hopping empty rows) / random / stop — with the dice drawn from the
project's seeded rng, so a probabilistic set replays identically from the
same project. Follow + chain compose: the chain launches scenes on its bar
schedule while follows churn inside them.

## 4. The grid is 12×8 on purpose

The PRD's 16-track ceiling puts cells under the 44 px touch floor on the
1280×400 bar; 12×8 keeps every cell a fingertip with the scene column and
stop keys still on screen. The portrait panel pages six tracks at a time.
(A layout test pins the floor.)

## 5. Recording rounds up; overdubs keep length

Arming an empty slot records into a scratch loop and rounds the take *up*
to whole bars at disarm (1.2 bars meant 2); arming a filled slot overdubs
at its existing length. Open notes close at disarm/stop/panic, and monitor
thru sounds the take on its track's output while it goes down.

## 6. What the tests assert

- Launch loops; empty pads are no-ops; bar quantize defers, "off" fires on
  the next tick; the outgoing voice is released at every switch.
- Scenes are states (absent tracks stop); follow next/stop/probability all
  behave, and probability is seeded — two engines from one project emit
  identical streams.
- Recording rounds up to bars, overdubs keep length, thru follows the
  track's routing, panic lands the take.
- Chains step on schedule, wrap, and refuse to start empty.
- Mute/reroute release cleanly; clip transpose/scale shape playback;
  the intensity pot scales the room; projects round-trip.
- Panel: every drawn control is a registered hit target, the grid holds
  the touch floor on the bar, and pressing every control at all three
  geometries leaves nothing hanging.

## Deferred (deliberately)

Sample clips on the DAC (suite Phase 4), full linear-DAW arrange view (out
of scope by PRD), audio input (ditto), MIDI-mapped grid controllers.
