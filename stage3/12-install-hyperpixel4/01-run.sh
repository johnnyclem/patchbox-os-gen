#!/bin/bash -e
# Pimoroni HyperPixel 4.0" rectangular — 800×480 @ 60 FPS, DPI, optional Goodix touch.
# Bookworm/Pi 5: in-tree KMS overlay (no legacy installer).
#
#   dtoverlay=vc4-kms-dpi-hyperpixel4
#
# IMPORTANT — GPIO: HyperPixel 4 DPI uses ~28 of the 40 pins (effectively the
# whole header for alternate functions). You CANNOT stack Blokas Pimidi /
# Pisound on the same header and get a working DPI panel. This stage:
#   • strips forced HDMI modes (Profile A leftovers)
#   • strips dtoverlay=pimidi + dtparam=i2c_arm / spi=on (pinmux conflicts)
#   • writes the official bare HyperPixel overlay
# Pimidi *packages* may still be installed (stage 11); only the DT overlay is
# dropped so the panel can light. Use USB MIDI on this profile.
#
# ENABLE_HYPERPIXEL4=1 enables this stage. Mutually exclusive with
# ENABLE_HDMI_ULTRAWIDE and ENABLE_WAVESHARE_DPI for a clean kiosk panel.

if [ "${ENABLE_HYPERPIXEL4}" != "1" ]; then
	echo "ENABLE_HYPERPIXEL4!=1 — skipping HyperPixel 4 setup"
	exit 0
fi

# Native panel is 800×480 landscape glass; kernel often presents 480×800 until
# rotated. Defaults below get a *picture first*; rotate later if needed.
W="${HYPERPIXEL_WIDTH:-800}"
H="${HYPERPIXEL_HEIGHT:-480}"
R="${HYPERPIXEL_REFRESH:-60}"
# none = stock overlay only (most reliable first bring-up on Pi 5).
# left|right|inverted|normal → dtoverlay ...,rotate=270|90|180|0 (degrees).
ROT="${HYPERPIXEL_ROTATE:-none}"
# Optional cmdline video=DPI-1:… (Pimoroni docs do NOT require this; default off).
SET_VIDEO="${HYPERPIXEL_CMDLINE_VIDEO:-0}"
# Allow experimental Pimidi stack (almost always blacks the panel). Default: drop.
KEEP_PIMIDI="${HYPERPIXEL_KEEP_PIMIDI:-0}"

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

if [ ! -f "${CONFIG_TXT}" ]; then
	echo "ERROR: ${CONFIG_TXT} missing"
	exit 1
fi

echo "HyperPixel 4: ${W}x${H}@${R} rotate=${ROT} video=${SET_VIDEO} keep_pimidi=${KEEP_PIMIDI}"

if [ "${ENABLE_PIMIDI}" = "1" ] && [ "${KEEP_PIMIDI}" != "1" ]; then
	echo "  NOTE: ENABLE_PIMIDI=1 but HyperPixel owns the header — stripping pimidi DT overlay."
	echo "        Packages stay installed; use USB MIDI or a non-DPI profile for TRS."
fi

# Strip prior panel blocks + anything that steals DPI pinmux
TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*)
			continue ;;
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*|dtoverlay=vc4-kms-dpi-generic*)
			continue ;;
		*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*)
			continue ;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			# Drop forced HDMI modes when DPI is primary
			continue ;;
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
		# Active SPI steals pins HyperPixel needs
		dtparam=spi=on)
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "${CONFIG_TXT}" > "${TMP}"

# KMS on Pi 5: vc4-kms-v3d is the base (firmware picks pi5 bits as needed).
if ! grep -qE '^dtoverlay=vc4-kms-v3d' "${TMP}"; then
	echo "dtoverlay=vc4-kms-v3d" >> "${TMP}"
fi
if ! grep -qE '^max_framebuffers=' "${TMP}"; then
	echo "max_framebuffers=2" >> "${TMP}"
fi

# Bare overlay is the known-good Pi 5 path (Pimoroni learn guide). Optional
# rotate= in *degrees* (270 = landscape "left") — do NOT pass 0..3.
OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4"
case "${ROT}" in
	none|"")
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4"
		;;
	normal|0)
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=0"
		;;
	right|90)
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=90"
		;;
	inverted|180)
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=180"
		;;
	left|270)
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=270"
		;;
	*)
		OVERLAY_LINE="dtoverlay=vc4-kms-dpi-hyperpixel4"
		;;
esac

cat >> "${TMP}" <<EOF

# --- HyperPixel 4.0 rectangular (${W}x${H}@${R}) ---
# Pimoroni DPI; in-tree on Bookworm/Pi 5. Touch = Goodix (soft I2C in overlay).
# https://learn.pimoroni.com/getting-started-with-hyperpixel-4
# https://github.com/pimoroni/hyperpixel4  (no legacy installer)
# First bring-up: leave rotate=none if the panel stays black with rotate=*.
# Do not enable dtparam=i2c_arm / spi — they DT-conflict with DPI (PSA #177).
${OVERLAY_LINE}
# --- end HyperPixel 4 ---
EOF

cat "${TMP}" > "${CONFIG_TXT}"
rm -f "${TMP}"
echo "  updated ${CONFIG_TXT}: ${OVERLAY_LINE}"

# Kernel cmdline: strip HDMI force modes. Optional DPI video= (default off —
# wrong WxH here is a common black-screen cause; the overlay carries timings).
if [ -f "${CMDLINE}" ]; then
	TMPC="$(mktemp)"
	sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g; s/ *video=DSI-1:[^ ]*//g' \
		"${CMDLINE}" > "${TMPC}.1"
	if [ "${SET_VIDEO}" = "1" ]; then
		PREFIX="video=DPI-1:${W}x${H}@${R}D"
		if ! grep -q "video=DPI-1:" "${TMPC}.1"; then
			sed "s/^/${PREFIX} /" "${TMPC}.1" > "${TMPC}.2"
		else
			cp "${TMPC}.1" "${TMPC}.2"
		fi
	else
		cp "${TMPC}.1" "${TMPC}.2"
	fi
	tr -s ' \t' ' ' < "${TMPC}.2" | sed 's/^ //;s/ $//' | tr -d '\n' > "${TMPC}"
	echo >> "${TMPC}"
	cat "${TMPC}" > "${CMDLINE}"
	rm -f "${TMPC}" "${TMPC}.1" "${TMPC}.2"
	echo "  cmdline: $(cat "${CMDLINE}")"
fi

# X11 path (optional desktop): Goodix + libinput
install -d "${ROOTFS_DIR}/etc/X11/xorg.conf.d"
install -m 644 files/40-libinput-hyperpixel4.conf \
	"${ROOTFS_DIR}/etc/X11/xorg.conf.d/40-libinput-hyperpixel4.conf"

# udev: ensure touch nodes are input-group readable (kmsdrm)
install -d "${ROOTFS_DIR}/etc/udev/rules.d"
install -m 644 files/99-hyperpixel4-touch.rules \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-hyperpixel4-touch.rules"

# Touch orientation for kmsdrm / libinput
install -d "${ROOTFS_DIR}/etc/udev/hwdb.d"
case "${ROT}" in
	left|270)
		MAT="0 -1 1 1 0 0"
		;;
	right|90)
		MAT="0 1 0 -1 0 1"
		;;
	inverted|180)
		MAT="-1 0 1 0 -1 1"
		;;
	*)
		MAT="1 0 0 0 1 0"
		;;
esac
cat > "${ROOTFS_DIR}/etc/udev/hwdb.d/61-hyperpixel4-touch.hwdb" <<EOF
# HyperPixel 4 rectangular Goodix — match display rotation (${ROT})
evdev:name:*Goodix*:
evdev:name:*goodix*:
 LIBINPUT_CALIBRATION_MATRIX=${MAT}
EOF

install -m 755 files/patchbox-hyperpixel-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-hyperpixel-status"
install -d "${ROOTFS_DIR}/usr/local/sbin"
install -m 755 files/patchbox-fix-hyperpixel4 \
	"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-hyperpixel4"

# LightDM stay-awake (if desktop is used)
LIGHTDM="${ROOTFS_DIR}/etc/lightdm/lightdm.conf"
if [ -f "${LIGHTDM}" ]; then
	if ! grep -q 'xserver-command=X -s 0 -dpms' "${LIGHTDM}"; then
		if grep -q '^#xserver-command=X' "${LIGHTDM}"; then
			TMPL="$(mktemp)"
			sed 's/^#xserver-command=X$/xserver-command=X -s 0 -dpms/' "${LIGHTDM}" > "${TMPL}"
			cat "${TMPL}" > "${LIGHTDM}"
			rm -f "${TMPL}"
		elif grep -q '^xserver-command=' "${LIGHTDM}"; then
			TMPL="$(mktemp)"
			sed 's/^xserver-command=.*/xserver-command=X -s 0 -dpms/' "${LIGHTDM}" > "${TMPL}"
			cat "${TMPL}" > "${LIGHTDM}"
			rm -f "${TMPL}"
		else
			printf '\n[Seat:*]\nxserver-command=X -s 0 -dpms\n' >> "${LIGHTDM}"
		fi
	fi
fi

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/HYPERPIXEL4.txt" <<EOF
Patchbox OS — HyperPixel 4.0" + RK-00pi
=======================================

Display
  Pimoroni HyperPixel 4.0" rectangular
  ${W}x${H} @ ${R} Hz  (DPI, 60 FPS panel)
  overlay: ${OVERLAY_LINE}
  rotate:  ${ROT}
  cmdline video=: ${SET_VIDEO} (0 = let overlay set timings — preferred)

Touch
  Goodix capacitive (soft I2C inside the overlay — not dtparam=i2c_arm).
  Under kmsdrm the rk00pi user needs group input.
  Check: patchbox-hyperpixel-status · libinput list-devices

GPIO / MIDI
  HyperPixel uses almost the entire 40-pin for DPI.
  Pimidi/Pisound DT overlays are stripped on this profile so the panel can
  paint. For TRS MIDI use Profile A (HDMI + Pimidi) or a USB MIDI interface.

  Field re-apply / convert HDMI image → DPI:
    sudo patchbox-fix-hyperpixel4
    sudo reboot

RK-00pi
  Panel size should be ${W}x${H} in /etc/rk00pi/config.toml
  800x480 uses the stacked chrome (top transport + bottom tabs)
  because aspect < 2:1 (see gui/theme.is_wide).

Checks
  patchbox-hyperpixel-status
  ls /sys/class/drm/card*-DPI-*/status
  dmesg | grep -iE 'dpi|vc4|drm|hyperpixel'
  # Healthy: a DPI connector status=connected with modes listed
  # Broken:  only HDMI connectors, or dmesg "Cannot find any crtc or sizes"
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/HYPERPIXEL4.txt" 2>/dev/null || true

echo "HyperPixel 4 configured: ${W}x${H}@${R} rotate=${ROT}"
