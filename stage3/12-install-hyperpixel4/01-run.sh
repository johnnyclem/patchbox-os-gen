#!/bin/bash -e
# Pimoroni HyperPixel 4.0" rectangular — 800×480 @ 60 FPS, DPI, optional Goodix touch.
# Bookworm/Pi 5: in-tree KMS overlay (no legacy installer).
#
#   dtoverlay=vc4-kms-dpi-hyperpixel4
#
# IMPORTANT — GPIO: HyperPixel 4 DPI uses nearly the entire 40-pin header.
# Stacking Blokas Pimidi on the same header is pin-contested (Pimidi needs I2C
# + a data GPIO). Prefer HyperPixel alone + USB MIDI, or accept that Pimidi
# may not enumerate. This stage does not remove the Pimidi overlay; it only
# configures the display path.
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

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

if [ ! -f "${CONFIG_TXT}" ]; then
	echo "ERROR: ${CONFIG_TXT} missing"
	exit 1
fi

echo "HyperPixel 4: ${W}x${H}@${R} rotate=${ROT}"

# Strip prior panel blocks we manage (HDMI ultrawide, Waveshare DPI, HyperPixel)
TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*)
			continue ;;
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*)
			continue ;;
		*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*)
			continue ;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			# Drop forced HDMI modes when DPI is primary
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "${CONFIG_TXT}" > "${TMP}"

# KMS on Pi 5: prefer pi5-named overlay when present in firmware later;
# vc4-kms-v3d is still required as the base.
if ! grep -qE '^dtoverlay=vc4-kms-v3d' "${TMP}"; then
	echo "dtoverlay=vc4-kms-v3d" >> "${TMP}"
fi
if ! grep -qE '^max_framebuffers=' "${TMP}"; then
	echo "max_framebuffers=2" >> "${TMP}"
fi

# PSA (pimoroni/hyperpixel4#177): generic i2c_arm / spi enable can DT-conflict
# with HyperPixel. Pimidi stage may have added a high-rate i2c_arm line —
# drop *only* that managed baudrate line so HyperPixel can claim the bus for
# Goodix; Pimidi's own overlay still brings up what it needs.
TMP2="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		dtparam=i2c_arm=on,i2c_arm_baudrate=*)
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "${TMP}" > "${TMP2}"
cat "${TMP2}" > "${TMP}"
rm -f "${TMP2}"

# Bare overlay is the known-good Pi 5 path. Optional rotate= in *degrees*
# (270 = landscape "left") — do NOT pass 0..3; that confuses some kernels.
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
# Pimoroni DPI; in-tree on Bookworm/Pi 5. Touch = Goodix I2C.
# https://github.com/pimoroni/hyperpixel4  (no legacy installer)
# First bring-up: leave rotate=none if the panel stays black with rotate=*.
${OVERLAY_LINE}
# --- end HyperPixel 4 ---
EOF

cat "${TMP}" > "${CONFIG_TXT}"
rm -f "${TMP}"
echo "  updated ${CONFIG_TXT}: ${OVERLAY_LINE}"

# Kernel mode: rectangular glass is 800x480; some kernels name the connector
# DPI-1. Also hint 480x800 (native portrait) so either orientation can attach.
if [ -f "${CMDLINE}" ]; then
	TMPC="$(mktemp)"
	sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g; s/ *video=DSI-1:[^ ]*//g' \
		"${CMDLINE}" > "${TMPC}.1"
	# Prefer native-ish modes; do not force HDMI.
	PREFIX="video=DPI-1:${W}x${H}@${R}D"
	if ! grep -q "video=DPI-1:" "${TMPC}.1"; then
		sed "s/^/${PREFIX} /" "${TMPC}.1" > "${TMPC}.2"
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

# Touch orientation for kmsdrm / libinput (landscape left default)
# Matrix for 90° CW (display left): 0 -1 1  1 0 0
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
Patchbox OS — HyperPixel 4.0" + Pimidi + RK-00pi
================================================

Display
  Pimoroni HyperPixel 4.0" rectangular
  ${W}x${H} @ ${R} Hz  (DPI, 60 FPS panel)
  overlay: ${OVERLAY_LINE}
  cmdline: video=DPI-1:${W}x${H}@${R}D
  rotate:  ${ROT} (touch matrix applied via udev hwdb)

Touch
  Goodix capacitive (I2C). Under kmsdrm the rk00pi user needs group input.
  X11: /etc/X11/xorg.conf.d/40-libinput-hyperpixel4.conf
  Check: patchbox-hyperpixel-status · libinput list-devices

GPIO warning
  HyperPixel uses almost the entire 40-pin for DPI.
  Blokas Pimidi also needs the header (I2C + data GPIO).
  Stacking both is pin-contested — if MIDI does not appear after boot:
    amidi -l ; aconnect -l ; dmesg | grep -i pimidi
  Fallbacks: USB MIDI host, or drop HyperPixel for HDMI bar + Pimidi.

RK-00pi
  Panel size should be ${W}x${H} in /etc/rk00pi/config.toml
  800x480 uses the portrait chrome (top transport + bottom tabs)
  because aspect < 2:1 (see gui/theme.is_wide).

Checks
  patchbox-hyperpixel-status
  kmsprint / cat /sys/class/drm/card*-DPI-1/modes
  patchbox-pimidi-status
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/HYPERPIXEL4.txt" 2>/dev/null || true

echo "HyperPixel 4 configured: ${W}x${H}@${R} rotate=${ROT}"
