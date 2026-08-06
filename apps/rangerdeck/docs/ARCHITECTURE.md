# RangerDeck — architecture

## 1. Why a separate process per app

Every Ranger app has top-level `core/` and `gui/` packages by family
convention, so two apps cannot share one interpreter without an import
war. More importantly, per-process guests keep the suite's deployment
isolation: an app that crashes, leaks, or gets rolled back takes nothing
else with it — the deck reaps it and its tile goes dark.

## 2. The pieces

| Piece | Role |
|-------|------|
| `core/registry.py` | which apps are on disk, and the argv to start each |
| `core/engine.py` | the fleet: spawn / attach / show / stop / reap |
| `gui/app.py` | the grid, and the blocking "visit" to a shown guest |
| `rangerkit/deck.py` | both halves of the socket protocol (shared) |

The fleet is the deck's "engine" by analogy: `core/` is stdlib-only (plus
rangerkit), headless-importable, and fully testable with injected fakes —
`spawn` and `connect` are constructor parameters.

## 3. States

    off ──launch──▶ starting ──attach──▶ background ◀──hidden── shown
                                     │                    ▲
                                     └───────show─────────┘

`background` is the product: the guest's engine thread keeps clock,
transport, arps, recording and playback alive with no display attached.
That costs nothing new — every app's GUI was already a pure client of its
engine ("closing the window stops the picture, not the routing").

## 4. The handover, precisely

Whoever is about to stop drawing closes its SDL display *before* the other
side opens one; the socket events are the fence. The deck blocks in
`fleet.wait_while_shown()` while a guest draws — there is nothing else it
could usefully do without a display — and polls guest liveness so a
crashed guest returns the panel within half a second. A guest that cannot
open the display (`SHOW` but no `SHOWN` inside 15 s, or an immediate
`HIDDEN`) is treated as hidden: the deck takes the panel back and the rig
stays up.

Signals: the deck unit's stop propagates SIGTERM to the whole cgroup;
`run_deck_session` turns it into a clean pygame QUIT (shown) or a wait
flag (hidden) so every guest closes its notes on the way down.

## 5. Sharing the hardware

* **MIDI** — every running guest holds its own ALSA seq client and hears
  every bound input. Two arps from two backgrounded apps both play; that
  is the point, and PANIC lives in each app.
* **Audio** — Groove/Synth follow `[audio] backend="auto"`: with JACK up
  they mix; bare ALSA hw is first-come-first-served and the loser degrades
  to null (its SET screen says so). One audio app at a time is the honest
  Profile A story.
* **The Button** — belongs to the boot app; `[button] enabled=false` on
  the deck. Guests spawned by the deck cannot bind /run/<app>/button.sock
  (no RuntimeDirectory of their own) and degrade silently, which is
  correct: every gesture has an on-screen equivalent.

## 6. Out of scope (deliberately)

RK-00pi tiles (submodule; no deck protocol), guest-to-guest transport
sync, a shared master clock, and remembering/restarting the fleet across
deck restarts.
