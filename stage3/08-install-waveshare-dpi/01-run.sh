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

W="${WAVESHARE_WIDTH:-640}"
H="${WAVESHARE_HEIGHT:-480}"
R="${WAVESHARE_REFRESH:-60}"
KEEP_PIMIDI="${WAVESHARE_KEEP_PIMIDI:-0}"

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
OVERLAY_DIR="${ROOTFS_DIR}/boot/firmware/overlays"
echo "Waveshare 3.5 DPI: ${W}x${H}@${R} keep_pimidi=${KEEP_PIMIDI}"

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
		# Other DPI / HyperPixel — only one panel owns the header
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*|dtoverlay=vc4-kms-dpi-generic*)
			continue ;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			continue ;;
		dtparam=spi=on)
			echo "#dtparam=spi=on"
			continue ;;
		dtparam=i2s=on)
			echo "#dtparam=i2s=on"
			continue ;;
		# Strip pimidi DT unless this profile opts in (stage 11 re-adds when KEEP=1)
		dtoverlay=pimidi*|dtparam=i2c_arm=*|dtparam=i2c_arm_baudrate=*)
			if [ "${KEEP_PIMIDI}" = "1" ]; then
				:
			else
				continue
			fi
			;;
		*'--- Pimidi'*|*'--- end Pimidi'*)
			if [ "${KEEP_PIMIDI}" = "1" ]; then
				:
			else
				continue
			fi
			;;
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
	cat >> "${TMP_CFG}" <<EOF

# --- Waveshare 3.5 DPI LCD (${W}x${H} IPS capacitive) ---
# Bookworm: https://www.waveshare.com/wiki/3.5inch_DPI_LCD
# DTBO files installed to /boot/firmware/overlays/
# GPIO: almost all pins used for DPI666 + touch I2C + backlight PWM (GPIO18).
# Free NC: physical pins 1, 17, 35, 37 only — I2S audio HAT will not work.
# Pimidi under this panel: WAVESHARE_KEEP_PIMIDI=${KEEP_PIMIDI} (experimental).
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
		sed "s/^/video=DPI-1:${W}x${H}M@${R} /" "${TMP_C}.1" > "${TMP_C}.2"
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
Patchbox OS — Waveshare 3.5" DPI LCD (${W}×${H} capacitive)
=========================================================

Hardware stack
  Raspberry Pi
    └── Blokas Pimidi (optional, keep_pimidi=${KEEP_PIMIDI})
          └── Waveshare 3.5inch DPI LCD
  Panel: ${W}×${H} IPS @ ${R}Hz via DPI666
  Touch: Goodix capacitive (I2C), glass cover
  Wiki:  https://www.waveshare.com/wiki/3.5inch_DPI_LCD

Boot config (Bookworm)
  dtoverlay=vc4-kms-v3d
  dtoverlay=waveshare-35dpi
  dtoverlay=waveshare-touch-35dpi
  cmdline: video=DPI-1:${W}x${H}M@${R}
  Overlays: /boot/firmware/overlays/waveshare-*.dtbo
  Backlight: waveshare-dpi-backlight.service (GPIO18 high)
  Pimidi: keep_pimidi=${KEEP_PIMIDI}  (dtoverlay=pimidi when 1)

GPIO
  DPI uses almost the entire header. Free NC: pins 1, 17, 35, 37.
  Stacking Pimidi under the panel is experimental — if the glass stays black
  or touch dies, set WAVESHARE_KEEP_PIMIDI=0 and use USB MIDI, or Profile A
  (HDMI + Pimidi).

Audio: USB interface if no other HAT; I2S will not work under DPI.

Black screen recovery
  1. Power off, reseat all 40 pins (not offset).
  2. SSH:
       sudo patchbox-fix-waveshare-dpi
       sudo reboot
  3. If still black:
       sudo pinctrl set 18 op dh
       sudo patchbox-display-status
       dmesg | grep -iE 'dpi|panel|goodix|pimidi'
  4. Fallback: uncomment in /boot/firmware/config.txt:
       #dtoverlay=vc4-kms-DPI-35inch
  5. Pimidi fight: comment out dtoverlay=pimidi, reboot; use USB MIDI.

Rotation (optional)
  video=DPI-1:${W}x${H}M@${R},rotate=90   # in cmdline.txt

RK-00pi panel size
  /etc/rk00pi/config.toml  width=${W} height=${H}
  Checks:  patchbox-display-status · patchbox-rk00pi-status
EOF

chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/WAVESHARE-DPI.txt" 2>/dev/null || true

# Optional on-screen keyboard (never fail the image build)
on_chroot << 'EOF' || true
	apt-get install -y squeekboard 2>/dev/null || apt-get install -y matchbox-keyboard 2>/dev/null || true
EOF

echo "Waveshare 3.5 DPI: overlays installed, config.txt updated for ${W}x${H} capacitive (keep_pimidi=${KEEP_PIMIDI})"
