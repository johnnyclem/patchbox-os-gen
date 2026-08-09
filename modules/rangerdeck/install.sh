#!/bin/sh
# RangerDeck is baked into the image by stage3/21. This module only needs
# the app present so the Patchbox module wizard can activate it like MODEP.
set -e
if [ ! -x /opt/rangerdeck/venv/bin/python ] && [ ! -f /opt/rangerdeck/main.py ]; then
	echo "rangerdeck is not installed on this image (missing /opt/rangerdeck)" >&2
	echo "Rebuild with ENABLE_RANGERDECK=1 or run: sudo patchbox-setup status" >&2
	exit 1
fi
if ! systemctl cat rangerdeck.service >/dev/null 2>&1; then
	echo "rangerdeck.service missing — image incomplete" >&2
	exit 1
fi
echo "rangerdeck module ready (/opt/rangerdeck)"
exit 0
