#!/bin/bash -e

install -m 644 files/*.service "${ROOTFS_DIR}/usr/lib/systemd/system"
install -m 755 -D files/patchbox-irq-priorities.sh "${ROOTFS_DIR}/usr/local/sbin/patchbox-irq-priorities.sh"
install -m 644 -D files/90-patchbox-audio.conf "${ROOTFS_DIR}/etc/sysctl.d/90-patchbox-audio.conf"

on_chroot << EOF
	systemctl daemon-reload

	systemctl enable cpu_performance_scaling_governor
	systemctl enable patchbox-irq-priorities
	systemctl disable raspi-config # raspi-config is only enabling 'ondemand' governor as of 2018.08.19

	cd /usr/local/pisound
	git fetch origin
	git checkout "${PISOUND_GIT_REF}"
EOF

if [ "${ENABLE_WIFI_HOTSPOT}" = "1" ]; then
	on_chroot << EOF
	systemctl enable wifi-hotspot
EOF
else
	on_chroot << EOF
	systemctl disable wifi-hotspot
EOF
fi
