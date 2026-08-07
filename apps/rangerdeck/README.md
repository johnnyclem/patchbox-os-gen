# RangerDeck — the Ranger Suite launcher

UI follows the **micro-rangers** industrial language (design handoff
2026-08-06): RADIUS 0, 2 px hard black rules, numbers in black LCD wells,
HOT orange focus rings, pad states (stopped / queued / playing), status
ribbon + encoder legend chrome.

One pad per Ranger app on the 1280×400 bar (4-column grid; portrait
panels get 2 columns). Tap a pad and the deck spawns that app and hands
it the panel; the ✕ the app grows in its top-left corner hands the panel
back. **Closing the picture never stops the music**: a backgrounded app
keeps its engine — clock, transport, arps, recording, playback — running
in its own process, and its pad shows ▶ RUNNING until you press the pad's
■ to shut the rig down for real. The last pad is **POWER**.

![The deck at rest — one tile per installed app](docs/img/deck-1280x400-0-idle.png)

![MidiRanger and GrooveRanger backgrounded, both tiles showing RUNNING](docs/img/deck-1280x400-1-running.png)

```
python main.py                     # 1280x400 window, dev box
python main.py --size 480x800     # portrait panel
python main.py --fullscreen       # the appliance
```

## How to launch an app (on the device)

The deck is a **tile grid**. Tap a coloured tile → that app takes the
panel. While it is open, the top-left **✕** hands the panel back (music
keeps running; the tile says RUNNING). Tap the tile again to re-show it;
the tile's **■** stops the rig for real.

The last cell is **POWER** (fills the empty square on a 7-app, 4-column
grid). Tap it for **Restart** / **Shut Down** / **Cancel**. Needs
`/etc/sudoers.d/rangerdeck-power` (baked by `stage3/21-install-rangerdeck`).

## Updates (git channel)

On launch the deck checks a tiny JSON channel file in the git repo you push
to (`apps/rangers-channel.json`). When the remote tip moves, the header
shows **UPDATE · TAP** → **Install** / **Later**. Install runs
`patchbox-ranger-update` (shallow clone + rsync into `/opt/*`, keeps venvs).

```bash
# After you ship a change:
git rev-parse --short HEAD   # paste into apps/rangers-channel.json
# edit version + notes, then:
git add apps/rangers-channel.json && git commit && git push

# On a unit (or from the panel Install button):
sudo patchbox-ranger-update          # apply
sudo patchbox-ranger-update --check  # compare only
```

Configure in `/etc/rangerdeck/config.toml`:

```toml
[updates]
enabled = true
check_on_launch = true
channel_url = "https://raw.githubusercontent.com/<you>/patchbox-os-gen/<branch>/apps/rangers-channel.json"
git_url = "https://github.com/<you>/patchbox-os-gen.git"
git_ref = "<branch>"
```

If the grid paints but **taps do nothing**, touch is not reaching the
app — not a "how do I load" mystery. Check HDMI *and* the USB touch cable,
then:

```
patchbox-display-status
sudo patchbox-touch-probe          # tap the glass; expect ABS/BTN lines
journalctl -u rangerdeck -b -n 40  # look for "touch: native (N device(s))"
```

Zero devices usually means the service user is not in group `input`.

## How the handover works

There is one panel and one DRM master, so the deck and its guests never
hold the display at once. The choreography (rangerkit/deck.py, one line
protocol over `/run/rangerdeck/<app>.sock`):

1. tap → deck spawns `<app>/main.py --deck-socket /run/rangerdeck/<app>.sock`
2. the guest builds its whole rig (engine, MIDI, button, pots, audio) and
   listens; the deck attaches
3. deck closes its own display, sends `SHOW`; guest opens the panel,
   answers `EVENT SHOWN`
4. guest's ✕ → guest closes its display *only*, sends `EVENT HIDDEN`;
   deck reopens the panel with the tile marked RUNNING
5. tile tap again → `SHOW` to the already-running guest (rig untouched);
   tile ■ → `QUIT`, the guest closes its notes and exits

Debuggable from the field the same way as the button bridge:

```
echo PING | nc -U /run/rangerdeck/midiranger.sock     # -> PONG
```

## Tests

```
cd apps/rangerdeck && python -m pytest -q     # headless: SDL dummy, fake
                                              # and real-socket fleets
python bench/render_panel.py docs/img         # grid screenshots
```

## On the image

Installed by `stage3/21-install-rangerdeck` like every sibling
(`/opt/rangerdeck`, `/etc/rangerdeck/config.toml`, `rangerdeck.service`).
Boot it with `RANGER_BOOT_APP=rangerdeck` at bake time (see
`config.rangers`) or `sudo patchbox-app enable rangerdeck` on the device.
Guests run as the deck's user and share writable data dirs through the
`ranger` group. RK-00pi is not a tile (it does not speak the deck protocol
yet); it remains one `patchbox-app enable rk00pi` away.
