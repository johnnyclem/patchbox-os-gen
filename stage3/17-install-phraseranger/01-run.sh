#!/bin/bash -e
# Install PhraseRanger — the MIDI phrase looper appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_PHRASERANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_PHRASERANGER}" != "1" ]; then
	echo "ENABLE_PHRASERANGER!=1 — skipping PhraseRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app phraseranger "PhraseRanger" \
	"MIDI phrase looper — capture, overdub, slice" \
	"${PHRASERANGER_WIDTH}" "${PHRASERANGER_HEIGHT}"
