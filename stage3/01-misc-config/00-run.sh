#!/bin/bash -e

# NOTE: SSH is enabled via the ENABLE_SSH config variable (see stage2/01-sys-tweaks),
# which correctly targets the FAT boot partition marker on bookworm. A prior
# `touch ${ROOTFS_DIR}/boot/ssh` here targeted the ext4 rootfs's /boot directory
# (a plain subdirectory, not the /boot/firmware vfat mount point that bookworm's
# sshswitch.service actually checks) and was a silent no-op.

# Set the new hostname.
CURRENT_HOSTNAME=$(tr -d " \t\n\r" < "${ROOTFS_DIR}/etc/hostname")
echo "$HOSTNAME" > "${ROOTFS_DIR}/etc/hostname"
sed -i 's/127.0.1.1.*'"$CURRENT_HOSTNAME"'/127.0.1.1\t'"$HOSTNAME"'/g' "${ROOTFS_DIR}/etc/hosts"

# Make a link from 'pi' home to the configured user.
# This is done in order to make the experience of using
# this image more seamless, as a lot of information or
# guides on the net use /home/pi in the commands.
on_chroot << EOF
	unlink /home/pi || true
	ln -s /home/${FIRST_USER_NAME} /home/pi
EOF

# Boot to console by default.
on_chroot << EOF
	systemctl set-default multi-user.target
	ln -fs /lib/systemd/system/getty@.service /etc/systemd/system/getty.target.wants/getty@tty1.service
EOF

# Set up sudoers.d for user patch
rm -f "${ROOTFS_DIR}/etc/sudoers.d/010_pi-nopasswd"
install -m 440 files/010_patch-nopasswd "${ROOTFS_DIR}/etc/sudoers.d/"
