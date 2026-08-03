#!/bin/bash -e
# Install GenRanger — the generative sequencer appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_GENRANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_GENRANGER}" != "1" ]; then
	echo "ENABLE_GENRANGER!=1 — skipping GenRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app genranger "GenRanger" \
	"Generative sequencer — Euclid, Markov, CA, Cruise" \
	"${GENRANGER_WIDTH}" "${GENRANGER_HEIGHT}"
