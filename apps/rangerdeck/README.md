# RangerDeck — the Ranger Suite launcher

One tile per Ranger app on the 1280×400 bar (4-column grid; portrait
panels get 2 columns). Tap a tile and the deck spawns that app and hands
it the panel; the ✕ the app grows in its top-left corner hands the panel
back. **Closing the picture never stops the music**: a backgrounded app
keeps its engine — clock, transport, arps, recording, playback — running
in its own process, and its tile says RUNNING until you press the tile's
■ to shut the rig down for real.

```
python main.py                     # 1280x400 window, dev box
python main.py --size 480x800     # portrait panel
python main.py --fullscreen       # the appliance
```

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
