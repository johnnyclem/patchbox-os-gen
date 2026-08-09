# Ranger Suite — UI/UX spec

The design system of record for every Ranger panel in this repo.

Source: the micro-rangers 320×240 design system master sheet (2026-08-06,
master PDF generated 2026-08-09), which is itself a companion to
`docs/micro-rangers/HANDOFF.md`.

**What is inherited and what is not.** The master sheet is drawn for the
micro-rangers panel — a 320×240 screen with two rotary encoders. This repo
builds the RK-00pi suite: a 1280×400 touch bar with two pots and one button.
The sheet says of its own ancestor, "inherit language from RK-00pi — not its
layouts", and the same line runs back the other way. So:

* **Inherited in full** — colour, type, geometry, state semantics, the touch
  floors, the interaction model, the rules about captions and press
  affordance. These are the *language*, they are hardware-independent, and
  they are what makes eight separate apps feel like one instrument.
* **Not inherited** — the fixed 18/206/16 band stack, the 8×5 LAUNCH grid,
  the ENC1/ENC2 legend strings, the ENC2-hold tab overlay. Those describe a
  panel and a pair of encoders this hardware does not have. Copying them
  would produce a legend that lies about the controls.

The implementation is `apps/rangerkit/gui/theme.py` (tokens, geometry) and
`apps/rangerkit/gui/widgets.py` (every control). There is exactly one copy of
each; the apps import them and must not re-derive a rule locally.
`apps/rangerkit/tests/test_design_system.py` asserts the checkable claims
below, so a divergence is a red build rather than a discovery.

## Tokens

The INDUSTRIAL colourway is the sheet's, verbatim, and is the default.

| Token | Value | Means |
|---|---|---|
| `BG` | `#0A0A0A` | panel ground |
| `BG_RAISED` | `#1A1A1A` | surface — button rest, pad rest |
| `BG_LCD` | `#0D1A20` | well |
| `TEXT` | `#E8E8E8` | body |
| `TEXT_DIM` | `#7A7A7A` | caption, legend |
| `ACCENT3` / `HOT` / `DISPLAY` | `#56D6FF` | **cyan** — selection, active route, every value in a well |
| `ACCENT` | `#FF6B2C` | **orange** — playing, recording |
| `ACCENT2` | `#8A3A18` | orange dimmed — armed, queued |
| `OK` | `#3DFF8A` | **green** — solo |
| `DANGER` | `#FF3D4A` | **red** — stop, delete, panic |
| `WARN` | `#FFD12A` | **yellow** — warn |

Semantics hold across every colourway. A scheme may re-tune a hue so it
survives its ground; it may not reassign what a hue *means*. In particular
selection is never orange (orange is transport state) and solo is never red.

Three colourways ship:

* **INDUSTRIAL** (default) — the sheet's palette.
* **NIGHT** — the same language a step off pure black, for panels whose
  backlight never fully closes.
* **DAYLIGHT** — the light-industrial scheme the RK-00pi bar shipped with
  before this pass. Kept, and kept selectable, because the finding behind it
  is real: a panel with a heavy blue cast and a shallow black collapses
  INDUSTRIAL's three near-black surfaces into one washed navy, and a filled
  pad stops being distinguishable from an empty one at arm's length. If that
  happens on a given unit, `colorway = "daylight"` in the app config is the
  whole fix.

`mono` and `dusk` were folded into NIGHT. Both still resolve, so a config or
a saved preference written earlier still boots the panel.

## Type

Five named steps — the sheet's four (9 / 7 / 6 / 5 px at 320×240) plus the
primary value — mapped onto this panel. Screens name a step rather than
picking a number, so a re-tune is one edit.

`TYPE_VALUE` 30 · `TYPE_TITLE` 18 · `TYPE_CAPTION` 14 · `TYPE_LABEL` 12 ·
`TYPE_MICRO` 10

Two families: a monospace for anything with a value in it, so digits do not
shift width as they count, and a grotesque for the display voice — headings,
buttons, tabs — always upper case.

## Geometry

* **Radius = 0** everywhere. There is no radius token because there is
  nowhere it could be anything else.
* **Rules = 2 px** (`BORDER_W`), never a hairline.
* **No shadows, no gradients, no blur.** Depth is lightness and the rule.
  There is no shadow token, and `panel()` does not take the keyword — a stale
  `shadow=True` is a `TypeError` at the call site, not a silent no-op.

## Touch floors

Two classes of control, two floors — the sheet's numbers exactly. They are a
*floor*, the point below which a control stops being reliably hittable, not a
target to design toward.

| Class | Floor | Behaviour |
|---|---|---|
| Direct-action | **40 × 36** | fires on press — transport, mute, solo, pads |
| Selectable | **28 × 24** | takes focus on press, edited afterwards |

Neither is square, and that matters: the bar is 400 px tall, so a grid forced
to 40 in both axes would give up a whole row to buy width nothing needs. Use
`theme.touch_ok(rect, direct=...)` rather than open-coding a number.

`TOUCH_MIN` (44) is what the rails and single-row strips actually aim for —
comfortably above the floor, because those have the room and a transport
button is the one control you press without looking.

## State

The states matrix, implemented once in `widgets.pad_face()`:

| State | Drawn as |
|---|---|
| empty | sunken fill |
| filled / stopped | surface fill, plus a mark |
| queued / armed | orange **dimmed** fill |
| playing | orange fill, inverse mark |
| recording | red fill |
| muted | dimmed — never hidden |
| pressed | inverse fill |
| selected | **cyan rule** (orthogonal to all of the above) |

Two rules are easy to break by accident and account for most of what this
pass fixed:

* **Press is geometry + inverse fill, never colour alone.** A control that
  only changes hue on press is invisible to a player looking at the keyboard,
  and indistinguishable from that control being *latched*.
* **Selection is a cyan rule or inverse video** — never a glow, never orange.
  A pad is routinely selected *and* playing, so one must be a fill and the
  other a rule.

Further: mute **dims and never hides**, so a muted track keeps its chip, its
name and its place in the row. Solo is **green emphasis**, and once anything
is soloed the rest dim — the only way to see at a glance that a silent track
is silent *because* of solo. An **active route is cyan**, not orange.

## Readouts

**Caption-over-value on every continuous parameter, and the caption is
permanent.** Nothing is hovered on a touch panel, so a caption that is not
always drawn is a caption nobody ever sees. `widgets.param()` is `lcd()` with
the caption made non-optional; use it for rate / gate / level / octave and
anything else that steps.

Values are cyan on the well, **never pure white on black** — white at value
size blooms on these panels and the digits smear together.

A meter is *output*. It shows what is coming out, pressing it does nothing,
and it is deliberately registered in no hit map.

## Interaction

* **Direct vs select-then-edit.** Direct-action controls fire on press.
  Selectable controls take focus on press and are edited afterwards.
* **Secondary actions live on long-press** (≥ 400–450 ms): mute a track, arm
  a clip, solo a voice, clear a lane, save over a scene.
* **The legend row is how long-press is discovered.** It is permanent, it
  sits at the bottom of the content band, and every screen sets `legend` (or
  overrides `legend_copy()` when the copy depends on what is focused).
  Without it, "hold a pad to mute it" is a feature only its author knows
  about. Copy names this panel's real controls — TAP, HOLD, − / + — and does
  not borrow the sheet's ENC1/ENC2.
* **Focus order** within a screen is left-to-right, top-to-bottom, chips
  before pads. Hit-map registration order is that order.
* No drag, no swipe, no inertia.

The legend costs 32 px of content height. `Layout.for_size(..., legend=True)`
carves it off the bottom, and declines to on a content band too short to give
it up — a legend that costs a screen its last usable row has stopped being a
help. A screen never has to know the legend exists; it just gets a slightly
shorter rect.

## Chrome

`Layout` decides where the chrome sits for one window size, and it is the
only place that knows the two orientations differ. On the bar, vertical space
is the scarce resource, so the chrome turns sideways — transport down the
left, tabs down the right, content keeps the height. A portrait panel gets
the ordinary top-bar/bottom-tabs stack.

The tab rail (`widgets.tab_rail`) and the transient notice
(`widgets.message_strip`) are shared, not copied per app: they were already
identical in all seven, and a tab rail that drifts between rangers is the
most obvious way for the suite to stop feeling like one instrument. The
current tab is inverse video — cyan ground, dark ink. The notice is a toast
in a well, not an orange panel; orange is transport state, and a notice that
borrows it makes the panel look like it started playing every time you save.

## House rule

Nothing in a GUI may capture a colour at import time — no `color=theme.X`
default arguments, no module-level colour tables. `theme.apply()` rebinds the
palette names in place, and a captured value would keep the old colourway
forever.
