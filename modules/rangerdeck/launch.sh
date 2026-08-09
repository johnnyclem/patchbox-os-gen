#!/bin/sh
# Hand the panel to the suite launcher. patchbox-app stands every other
# kiosk unit down so SDL kmsdrm never races for DRM master.
set -e
if [ -x /usr/local/bin/patchbox-app ]; then
	/usr/local/bin/patchbox-app enable rangerdeck
else
	systemctl stop rk00pi chordranger midiranger genranger phraseranger \
		sceneranger grooveranger synthranger 2>/dev/null || true
	systemctl disable rk00pi chordranger midiranger genranger phraseranger \
		sceneranger grooveranger synthranger 2>/dev/null || true
	systemctl enable rangerdeck.service
	systemctl restart rangerdeck.service
fi
