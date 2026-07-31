#!/bin/bash -e
# Waveshare 3.5" DPI LCD — 640×480 IPS, capacitive (Goodix) touch, 40-pin.
# https://www.waveshare.com/wiki/3.5inch_DPI_LCD
#
# IMPORTANT: DPI666 uses almost the entire GPIO header. You cannot stack
# Inky e-paper or RaspiAudio I2S on the same 40-pin with this panel.
# Use USB audio (+ future USB MIDI) for I/O.
#
# Note: this script runs on the pi-gen *host* (Debian container), not only
# in the chroot — keep it to bash/sed/grep (no python3).

if [ "${ENABLE_WAVESHARE_DPI}" != "1" ]; then
	echo "ENABLE_WAVESHARE_DPI!=1 — skipping Waveshare 3.5 DPI setup"
	exit 0
fi

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
OVERLAY_DIR="${ROOTFS_DIR}/boot/firmware/overlays"

install -d "${OVERLAY_DIR}"
install -m 644 files/overlays/*.dtbo "${OVERLAY_DIR}/"

if [ ! -f "${CONFIG_TXT}" ]; then
	echo "ERROR: ${CONFIG_TXT} missing"
	exit 1
fi

# Filter config.txt into a temp file (avoid sed -i host quirks).
TMP_CFG="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}" # ltrim
	case "${s}" in
		dtoverlay=spi0-0cs*|dtoverlay=i2c1|dtoverlay=i2c1,*|dtoverlay=i2c1-pi5*)
			continue ;;
		dtoverlay=googlevoicehat-soundcard*|dtoverlay=wm8960-soundcard*)
			continue ;;
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*)
			continue ;;
		dtoverlay=vc4-kms-DPI-35inch*|dtoverlay=waveshare-35dpi-3b*|dtoverlay=waveshare-35dpi-4b*)
			continue ;;
		dtparam=spi=on)
			echo "#dtparam=spi=on"
			continue ;;
		dtparam=i2s=on)
			echo "#dtparam=i2s=on"
			continue ;;
		hdmi_group=*)
			echo "#${s}"
			continue ;;
		hdmi_mode=*)
			echo "#${s}"
			continue ;;
		hdmi_force_hotplug=*)
			echo "#${s}"
			continue ;;
		*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*)
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "${CONFIG_TXT}" > "${TMP_CFG}"

# Ensure required lines
if ! grep -qE '^dtparam=i2c_arm=on' "${TMP_CFG}"; then
	echo "dtparam=i2c_arm=on" >> "${TMP_CFG}"
fi
if ! grep -qE '^dtoverlay=vc4-kms-v3d' "${TMP_CFG}"; then
	echo "dtoverlay=vc4-kms-v3d" >> "${TMP_CFG}"
fi

if ! grep -qE '^max_framebuffers=' "${TMP_CFG}"; then
	echo "max_framebuffers=2" >> "${TMP_CFG}"
fi

if ! grep -qE '^dtoverlay=waveshare-35dpi$' "${TMP_CFG}"; then
	cat >> "${TMP_CFG}" <<'EOF'

# --- Waveshare 3.5 DPI LCD (640x480 IPS capacitive) ---
# Bookworm: https://www.waveshare.com/wiki/3.5inch_DPI_LCD
# DTBO files installed to /boot/firmware/overlays/
# GPIO: almost all pins used for DPI666 + touch I2C + backlight PWM (GPIO18).
# Free NC: physical pins 1, 17, 35, 37 only — no I2S audio HAT stacking.
dtoverlay=waveshare-35dpi
dtoverlay=waveshare-touch-35dpi
# Fallback if still black (uncomment ONE line, reboot):
#dtoverlay=vc4-kms-DPI-35inch
# --- end Waveshare ---
EOF
fi

cat "${TMP_CFG}" > "${CONFIG_TXT}"
rm -f "${TMP_CFG}"
echo "Updated ${CONFIG_TXT}"

# Force DPI mode on the kernel cmdline (helps when no HDMI is attached).
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
if [ -f "${CMDLINE}" ]; then
	TMP_C="$(mktemp)"
	# Strip prior DPI video= tokens
	sed -E 's/ *video=DPI-1:[^ ]*//g' "${CMDLINE}" > "${TMP_C}.1"
	if ! grep -q 'video=DPI-1:' "${TMP_C}.1"; then
		sed 's/^/video=DPI-1:640x480M@60 /' "${TMP_C}.1" > "${TMP_C}.2"
	else
		cp "${TMP_C}.1" "${TMP_C}.2"
	fi
	# Collapse to a single clean line
	tr -s ' \t' ' ' < "${TMP_C}.2" | sed 's/^ //;s/ $//' | tr -d '\n' > "${TMP_C}"
	echo >> "${TMP_C}"
	cat "${TMP_C}" > "${CMDLINE}"
	rm -f "${TMP_C}" "${TMP_C}.1" "${TMP_C}.2"
	echo "Updated ${CMDLINE}: $(cat "${CMDLINE}")"
fi

# LightDM: never blank the small appliance panel
LIGHTDM="${ROOTFS_DIR}/etc/lightdm/lightdm.conf"
if [ -f "${LIGHTDM}" ]; then
	if grep -q 'xserver-command=X -s 0 -dpms' "${LIGHTDM}"; then
		:
	elif grep -q '^#xserver-command=X' "${LIGHTDM}"; then
		# Portable in-place: rewrite via temp
		TMP_L="$(mktemp)"
		sed 's/^#xserver-command=X$/xserver-command=X -s 0 -dpms/' "${LIGHTDM}" > "${TMP_L}"
		cat "${TMP_L}" > "${LIGHTDM}"
		rm -f "${TMP_L}"
	elif grep -q '^xserver-command=' "${LIGHTDM}"; then
		TMP_L="$(mktemp)"
		sed 's/^xserver-command=.*/xserver-command=X -s 0 -dpms/' "${LIGHTDM}" > "${TMP_L}"
		cat "${TMP_L}" > "${LIGHTDM}"
		rm -f "${TMP_L}"
	elif grep -q '^\[Seat' "${LIGHTDM}"; then
		TMP_L="$(mktemp)"
		# Insert after first [Seat...] line
		awk '
			BEGIN { done=0 }
			/^\[Seat/ && !done { print; print "xserver-command=X -s 0 -dpms"; done=1; next }
			{ print }
			END { if (!done) print "\n[Seat:*]\nxserver-command=X -s 0 -dpms" }
		' "${LIGHTDM}" > "${TMP_L}"
		cat "${TMP_L}" > "${LIGHTDM}"
		rm -f "${TMP_L}"
	else
		printf '\n[Seat:*]\nxserver-command=X -s 0 -dpms\n' >> "${LIGHTDM}"
	fi
	echo "Updated ${LIGHTDM}"
fi

# Xorg + udev
install -d "${ROOTFS_DIR}/etc/X11/xorg.conf.d"
install -m 644 files/40-libinput-waveshare.conf \
	"${ROOTFS_DIR}/etc/X11/xorg.conf.d/40-libinput-waveshare.conf"

install -d "${ROOTFS_DIR}/etc/udev/rules.d"
install -m 644 files/99-waveshare-touch.rules \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch.rules"

install -m 755 files/patchbox-display-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-display-status"
install -m 755 files/patchbox-fix-waveshare-dpi \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-fix-waveshare-dpi"

install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
install -m 644 files/waveshare-dpi-backlight.service \
	"${ROOTFS_DIR}/usr/lib/systemd/system/waveshare-dpi-backlight.service"

on_chroot << EOF
	systemctl daemon-reload
	systemctl enable waveshare-dpi-backlight.service
EOF
# (on_chroot is provided by pi-gen; failure here should fail the build)

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/WAVESHARE-DPI.txt" <<EOF
Patchbox OS — Waveshare 3.5" DPI LCD (640×480 capacitive)
=========================================================

Hardware
  Waveshare 3.5inch DPI LCD on the 40-pin header (on top of the Pi).
  Panel: 640×480 IPS @ 60Hz via DPI666
  Touch: Goodix capacitive (I2C), 5-point, glass cover
  Wiki:  https://www.waveshare.com/wiki/3.5inch_DPI_LCD

Boot config (Bookworm)
  dtoverlay=vc4-kms-v3d
  dtoverlay=waveshare-35dpi
  dtoverlay=waveshare-touch-35dpi
  cmdline: video=DPI-1:640x480M@60
  Overlays: /boot/firmware/overlays/waveshare-*.dtbo
  Backlight: waveshare-dpi-backlight.service (GPIO18 high)

GPIO — exclusive header
  Free NC only: physical pins 1, 17, 35, 37.
  Do NOT stack Inky, RaspiAudio, Pisound, or Pimidi on this header.

Audio: USB interface for JACK (I2S HAT will not work under DPI).

Black screen recovery
  1. Power off, reseat HAT on all 40 pins (not offset).
  2. SSH in and run:
       sudo patchbox-fix-waveshare-dpi
       sudo reboot
  3. If still black:
       sudo pinctrl set 18 op dh          # force backlight
       sudo patchbox-display-status
       dmesg | grep -iE 'dpi|panel|goodix'
  4. Fallback: edit /boot/firmware/config.txt, uncomment:
       #dtoverlay=vc4-kms-DPI-35inch
     then reboot.

Rotation (optional)
  video=DPI-1:640x480M@60,rotate=90   # in cmdline.txt
EOF

chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/WAVESHARE-DPI.txt" 2>/dev/null || true

# Optional on-screen keyboard (never fail the image build)
on_chroot << 'EOF' || true
	apt-get install -y squeekboard 2>/dev/null || apt-get install -y matchbox-keyboard 2>/dev/null || true
EOF

echo "Waveshare 3.5 DPI: overlays installed, config.txt updated for 640x480 capacitive"
