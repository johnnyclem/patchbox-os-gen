#!/bin/bash -e
# HDMI bar / ultrawide panel + USB HID touch.
#
# Default (Profile A): generic 1280×400 via hdmi_cvt + video=…@60D
# Waveshare 7.9" (Profile D): native 400×1280 wiki timings, app 400×1280,
#   NO kernel rotate — SDL kmsdrm does not honour video=…,rotate= the same
#   way the console does; rotate+1280×400 → 3× wrapped UI then black.
#
# Env:
#   ENABLE_HDMI_ULTRAWIDE=1
#   HDMI_WIDTH / HDMI_HEIGHT / HDMI_REFRESH  — app-facing geometry (after rotate)
#   HDMI_TIMINGS                             — if set, write hdmi_timings=… (not cvt)
#   HDMI_NATIVE_WIDTH / HDMI_NATIVE_HEIGHT   — cmdline mode before rotate
#   HDMI_ROTATE                              — 90|180|270 (empty = no rotate)
#   HDMI_CONNECTOR                           — default HDMI-A-1
#
# Runs on the pi-gen host: bash only (no python3).

if [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	echo "ENABLE_HYPERPIXEL4=1 — skipping ultrawide HDMI setup (DPI owns panel)"
	exit 0
fi

if [ "${ENABLE_WAVESHARE_DPI}" = "1" ]; then
	echo "ENABLE_WAVESHARE_DPI=1 — skipping ultrawide HDMI setup (DPI owns panel)"
	exit 0
fi

if [ "${ENABLE_HDMI_ULTRAWIDE}" != "1" ]; then
	echo "ENABLE_HDMI_ULTRAWIDE!=1 — skipping ultrawide HDMI setup"
	exit 0
fi

# App-facing size (what SDL / rk00pi open the window as).
W="${HDMI_WIDTH:-1280}"
H="${HDMI_HEIGHT:-400}"
R="${HDMI_REFRESH:-60}"
CONN="${HDMI_CONNECTOR:-HDMI-A-1}"
# Panel native pixel clock geometry (before KMS rotation). Empty → same as W×H.
NW="${HDMI_NATIVE_WIDTH:-}"
NH="${HDMI_NATIVE_HEIGHT:-}"
ROT="${HDMI_ROTATE:-}"
TIMINGS="${HDMI_TIMINGS:-}"

if [ -z "${NW}" ] || [ -z "${NH}" ]; then
	NW="${W}"
	NH="${H}"
fi

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

if [ ! -f "${CONFIG_TXT}" ]; then
	echo "ERROR: ${CONFIG_TXT} missing"
	exit 1
fi

# Strip prior custom HDMI / Waveshare DPI blocks we manage
TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*)
			continue ;;
		*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_timings=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "${CONFIG_TXT}" > "${TMP}"

# Ensure KMS present
if ! grep -qE '^dtoverlay=vc4-kms-v3d' "${TMP}"; then
	echo "dtoverlay=vc4-kms-v3d" >> "${TMP}"
fi
if ! grep -qE '^max_framebuffers=' "${TMP}"; then
	echo "max_framebuffers=2" >> "${TMP}"
fi

# Mode line: Waveshare 7.9 needs exact hdmi_timings (wiki); generic bars use cvt.
if [ -n "${TIMINGS}" ]; then
	MODE_LINE="hdmi_timings=${TIMINGS}"
	MODE_NOTE="hdmi_timings (vendor) for native ${NW}x${NH}"
else
	# hdmi_cvt: width height framerate aspect margins interlace rb
	# aspect 6 = 15:9 (closest stock token for very wide panels)
	MODE_LINE="hdmi_cvt=${W} ${H} ${R} 6 0 0 0"
	MODE_NOTE="hdmi_cvt ${W}x${H}@${R}"
fi

cat >> "${TMP}" <<EOF

# --- HDMI ultrawide / bar panel (app ${W}x${H}@${R}; native ${NW}x${NH}) ---
# Stack: Pimidi/Pisound on 40-pin; display = HDMI + USB touch (no GPIO).
# ${MODE_NOTE}
hdmi_force_hotplug=1
hdmi_ignore_edid=0xa5000080
hdmi_group=2
hdmi_mode=87
${MODE_LINE}
hdmi_drive=2
# --- end HDMI ultrawide ---
EOF

cat "${TMP}" > "${CONFIG_TXT}"
rm -f "${TMP}"
echo "Updated ${CONFIG_TXT} (${MODE_NOTE})"

# Kernel mode hint (KMS). Prefer HDMI-A-1; Pi 5 may use HDMI-A-1 or HDMI-A-2.
# Waveshare wiki documents rotate=90 for desktop; we only emit rotate when
# HDMI_ROTATE is set (not recommended for SDL kmsdrm kiosk — see profile D).
if [ -f "${CMDLINE}" ]; then
	TMPC="$(mktemp)"
	# Strip prior video=HDMI tokens we own
	sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' "${CMDLINE}" > "${TMPC}.1"
	if [ -n "${ROT}" ]; then
		# Wiki-style token; prefer matching app size to native mode instead.
		VTOKEN="video=${CONN}:${NW}x${NH}M@${R},rotate=${ROT}"
	elif [ -n "${TIMINGS}" ]; then
		# Vendor panel: M@ token matches Waveshare docs (without rotate).
		VTOKEN="video=${CONN}:${NW}x${NH}M@${R}"
	else
		VTOKEN="video=${CONN}:${NW}x${NH}@${R}D"
	fi
	if ! grep -q "video=${CONN}:" "${TMPC}.1"; then
		sed "s/^/${VTOKEN} /" "${TMPC}.1" > "${TMPC}.2"
	else
		# Replace leftover same-connector token if any slipped through
		sed -E "s#video=${CONN}:[^ ]*#${VTOKEN}#g" "${TMPC}.1" > "${TMPC}.2"
	fi
	tr -s ' \t' ' ' < "${TMPC}.2" | sed 's/^ //;s/ $//' | tr -d '\n' > "${TMPC}"
	echo >> "${TMPC}"
	cat "${TMPC}" > "${CMDLINE}"
	rm -f "${TMPC}" "${TMPC}.1" "${TMPC}.2"
	echo "Updated ${CMDLINE}: $(cat "${CMDLINE}")"
fi

# LightDM: keep panel awake
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

# Touch: USB HID (ElecLab bar, Waveshare 7.9 capacitive, and kin).
install -d "${ROOTFS_DIR}/etc/X11/xorg.conf.d"
install -m 644 files/40-libinput-touch.conf \
	"${ROOTFS_DIR}/etc/X11/xorg.conf.d/40-libinput-touch.conf"
install -d "${ROOTFS_DIR}/etc/udev/rules.d"
install -m 644 files/99-patchbox-touch.rules \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-patchbox-touch.rules"
# When the FB is rotated, libinput needs a matching matrix (Waveshare wiki).
rm -f "${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate90.rules" \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate180.rules" \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate270.rules" 2>/dev/null || true
if [ "${ROT}" = "90" ]; then
	install -m 644 files/99-waveshare-touch-rotate90.rules \
		"${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate90.rules"
elif [ "${ROT}" = "180" ]; then
	cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate180.rules" <<'UDEV'
# 180° display rotate → invert both axes
ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="-1 0 1 0 -1 1"
UDEV
elif [ "${ROT}" = "270" ]; then
	cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-waveshare-touch-rotate270.rules" <<'UDEV'
# 270° (90° CCW) — Waveshare wiki matrix
ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"
UDEV
fi

install -d "${ROOTFS_DIR}/usr/local/bin"
install -d "${ROOTFS_DIR}/usr/local/sbin"
install -m 755 files/patchbox-display-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-display-status"
install -m 755 files/patchbox-touch-probe \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-touch-probe"
install -m 755 files/patchbox-soak \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-soak"
# On-device Waveshare 7.9 rescue (also used by patchbox-setup display set).
# Safe to ship on every HDMI image — only rewrites boot files when run.
if [ -f "${BASE_DIR}/scripts/fix-waveshare79-bootfs.sh" ]; then
	install -m 755 "${BASE_DIR}/scripts/fix-waveshare79-bootfs.sh" \
		"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-waveshare79"
fi
if [ -f "${BASE_DIR}/SOAK-PROFILE-A.md" ]; then
	install -m 644 "${BASE_DIR}/SOAK-PROFILE-A.md" \
		"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/SOAK-PROFILE-A.md"
	install -d "${ROOTFS_DIR}/usr/share/doc/patchbox"
	install -m 644 "${BASE_DIR}/SOAK-PROFILE-A.md" \
		"${ROOTFS_DIR}/usr/share/doc/patchbox/SOAK-PROFILE-A.md"
fi

# Compact LXDE panel height for a short bar
if [ -f "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel" ]; then
	TMPP="$(mktemp)"
	sed -E 's/^height=[0-9]+/height=28/' \
		"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel" > "${TMPP}" || true
	if [ -s "${TMPP}" ]; then
		cat "${TMPP}" > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel"
	fi
	rm -f "${TMPP}"
fi

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
if [ -n "${TIMINGS}" ]; then
	PANEL_NAME="Waveshare 7.9\" HDMI LCD (native ${NW}×${NH}, rotate=${ROT:-none})"
	CFG_DOC="hdmi_group=2 / hdmi_mode=87 / hdmi_timings=${TIMINGS}"
	CMD_DOC="video=${CONN}:${NW}x${NH}M@${R},rotate=${ROT}"
else
	PANEL_NAME="HDMI bar ${W}×${H}"
	CFG_DOC="hdmi_group=2 / hdmi_mode=87 / hdmi_cvt=${W} ${H} ${R} 6 0 0 0"
	CMD_DOC="video=${CONN}:${NW}x${NH}@${R}D"
fi

cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/DISPLAY-PISOUND.txt" <<EOF
Patchbox OS — ${PANEL_NAME}
=================================================

Hardware stack
  Raspberry Pi 5
  + Pimidi or Pisound on the 40-pin (MIDI / audio)
  + HDMI panel + USB touch cable

Display
  App window:  ${W}x${H}@${R}  (rk00pi / rangers)
  config.txt:  ${CFG_DOC}
  cmdline:     ${CMD_DOC}
  Connector:   ${CONN}  (Pi 5: try HDMI-A-2 if blank — nearest-USB-C is A-1)

Waveshare 7.9" notes
  Wiki: https://www.waveshare.com/wiki/7.9inch_HDMI_LCD
  Native mode is 400×1280 (tall). The kiosk uses that size directly (portrait
  chrome). Do NOT pair rotate=90 with a 1280×400 app under SDL kmsdrm — you
  get three wrapped portrait strips then a black panel.
  Touch USB must be plugged in. Rear "Rotate Touch" if axes feel wrong.
  Brightness: long-press ON/OFF on the rear of the LCD. If USB power is weak
  at high brightness, feed 5V/2A into the panel Power port.

Touch checks
  patchbox-display-status
  patchbox-touch-probe
  lsusb ; cat /proc/bus/input/devices
  ls -l /dev/input/event* ; id rk00pi

Audio / MIDI
  Prefer Pimidi/Pisound for performance audio — not HDMI audio.
  aplay -l ; amidi -l ; jack_lsp

Checks
  cat /boot/firmware/config.txt | grep -E 'hdmi_|dtoverlay=vc4'
  cat /boot/firmware/cmdline.txt
  patchbox-display-status
  sudo patchbox-soak

Power saving
  LightDM: X -s 0 -dpms (panel stays on)
EOF

chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/DISPLAY-PISOUND.txt" 2>/dev/null || true

on_chroot << 'EOF' || true
	apt-get install -y squeekboard 2>/dev/null || apt-get install -y matchbox-keyboard 2>/dev/null || true
EOF

echo "HDMI panel: app ${W}x${H}@${R} native ${NW}x${NH} rotate=${ROT:-none} configured"
