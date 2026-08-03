#!/bin/bash -e
# Install MidiRanger — the MIDI matrix / arps / note FX appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_MIDIRANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_MIDIRANGER}" != "1" ]; then
	echo "ENABLE_MIDIRANGER!=1 — skipping MidiRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app midiranger "MidiRanger" \
	"MIDI matrix, arps and note FX" \
	"${MIDIRANGER_WIDTH}" "${MIDIRANGER_HEIGHT}"
