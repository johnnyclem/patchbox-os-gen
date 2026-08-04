#!/bin/bash -e
# Install SynthRanger — the multi-engine polysynth appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_SYNTHRANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_SYNTHRANGER}" != "1" ]; then
	echo "ENABLE_SYNTHRANGER!=1 — skipping SynthRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app synthranger "SynthRanger" \
	"Multi-engine polysynth — VA, FM, wavetable, phase distortion" \
	"${SYNTHRANGER_WIDTH}" "${SYNTHRANGER_HEIGHT}"
