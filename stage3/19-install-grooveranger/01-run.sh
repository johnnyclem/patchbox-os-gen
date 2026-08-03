#!/bin/bash -e
# Install GrooveRanger — the sample-groovebox appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_GROOVERANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_GROOVERANGER}" != "1" ]; then
	echo "ENABLE_GROOVERANGER!=1 — skipping GrooveRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app grooveranger "GrooveRanger" \
	"Sample groovebox — pads, step sequencer, song mode, FX bus" \
	"${GROOVERANGER_WIDTH}" "${GROOVERANGER_HEIGHT}"
