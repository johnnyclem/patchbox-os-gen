#!/bin/sh
# RK-00pi is baked by stage3/10. Module activation only needs the unit.
set -e
if [ ! -f /opt/rk00pi/main.py ]; then
	echo "rk00pi is not installed on this image (missing /opt/rk00pi)" >&2
	exit 1
fi
if ! systemctl cat rk00pi.service >/dev/null 2>&1; then
	echo "rk00pi.service missing — image incomplete" >&2
	exit 1
fi
echo "rk00pi module ready (/opt/rk00pi)"
exit 0
