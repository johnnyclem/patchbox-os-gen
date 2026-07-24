#!/bin/bash -e

# Setup VNC server.
if [ "${ENABLE_VNC}" = "1" ]; then
	on_chroot << EOF
	systemctl enable vncserver-x11-serviced.service
EOF
else
	on_chroot << EOF
	systemctl disable vncserver-x11-serviced.service
EOF
fi

# Telemetry is opt-out: the package stays installed either way, only its
# unit is disabled when ENABLE_TELEMETRY=0.
if [ "${ENABLE_TELEMETRY}" != "1" ]; then
	on_chroot << EOF
	systemctl disable blokas-telemetry || true
EOF
fi
