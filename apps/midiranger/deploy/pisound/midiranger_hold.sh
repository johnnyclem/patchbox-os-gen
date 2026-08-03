#!/bin/sh
# MidiRanger — hold actions. Map this to HOLD_1S/3S/5S/HOLD_OTHER in
# /etc/pisound.conf. pisound-btn passes the click count as $1 and the seconds
# held as $2.
#
# Safety net: if the instrument is not listening and the button was held past
# ~7 s, fall through to a clean shutdown. A crashed unit on a stage should
# still be switchable-off by the only control it has, rather than needing a
# power yank that risks the card.
[ -r /usr/local/pisound/scripts/common/common.sh ] &&
    . /usr/local/pisound/scripts/common/common.sh

CLICKS="${1:-1}"
SECONDS_HELD="${2:-0}"

/usr/local/bin/midiranger-btn HOLD "${CLICKS}" "${SECONDS_HELD}"
status=$?
if [ "${status}" -eq 2 ]; then
    command -v flash_leds >/dev/null 2>&1 && flash_leds 200
    command -v log >/dev/null 2>&1 &&
        log "midiranger: no instrument on the button socket"
    if [ "${SECONDS_HELD}" -ge 7 ] 2>/dev/null; then
        command -v log >/dev/null 2>&1 &&
            log "midiranger: no instrument, ${SECONDS_HELD}s hold — shutting down"
        shutdown -h now
    fi
fi
exit "${status}"
