#!/bin/sh
# ChordRanger — click actions. Map this to CLICK_1/2/3/CLICK_OTHER in
# /etc/pisound.conf (or via `sudo pisound-config`). pisound-btn passes the
# click count as $1; ChordRanger's own [button.map] decides what each count
# does, so this script never needs editing to rebind a gesture.
[ -r /usr/local/pisound/scripts/common/common.sh ] &&
    . /usr/local/pisound/scripts/common/common.sh

/usr/local/bin/chordranger-btn CLICK "${1:-1}"
status=$?
if [ "${status}" -eq 2 ]; then
    # Nothing listening: one long blink, and a line in the button log so
    # `journalctl -u pisound-btn` explains a dead button.
    command -v flash_leds >/dev/null 2>&1 && flash_leds 200
    command -v log >/dev/null 2>&1 &&
        log "chordranger: no instrument on the button socket"
fi
exit "${status}"
