#!/bin/bash -e
# HDMI ultrawide bar display (default 1280x400) + USB HID touch.
# Complements Pisound on the 40-pin — no GPIO display pin fights.
#
# Runs on the pi-gen host: bash only (no python3).

if [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	echo "ENABLE_HYPERPIXEL4=1 — skipping ultrawide HDMI setup (DPI owns panel)"
	exit 0
fi

if [ "${ENABLE_HDMI_ULTRAWIDE}" != "1" ]; then
	echo "ENABLE_HDMI_ULTRAWIDE!=1 — skipping ultrawide HDMI setup"
	exit 0
fi

W="${HDMI_WIDTH:-1280}"
H="${HDMI_HEIGHT:-400}"
R="${HDMI_REFRESH:-60}"

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
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
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

# Custom DMT mode 87 via CVT (works for many HDMI bar panels when EDID is odd)
# hdmi_cvt: width height framerate aspect margins interlace rb
# aspect 6 = 15:9 (closest stock token for very wide panels)
cat >> "${TMP}" <<EOF

# --- HDMI ultrawide / bar panel (${W}x${H}@${R}) ---
# Stack: Pisound on 40-pin; display = HDMI + USB touch (no GPIO).
# If the monitor's EDID already reports ${W}x${H}, these still force a stable mode.
hdmi_force_hotplug=1
hdmi_ignore_edid=0xa5000080
hdmi_group=2
hdmi_mode=87
hdmi_cvt=${W} ${H} ${R} 6 0 0 0
hdmi_drive=2
# --- end HDMI ultrawide ---
EOF

cat "${TMP}" > "${CONFIG_TXT}"
rm -f "${TMP}"
echo "Updated ${CONFIG_TXT} for ${W}x${H}@${R}"

# Kernel mode hint (KMS). Prefer HDMI-A-1; Pi 5 may use HDMI-A-1 or HDMI-A-2.
if [ -f "${CMDLINE}" ]; then
	TMPC="$(mktemp)"
	# Strip prior video=HDMI tokens we own
	sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' "${CMDLINE}" > "${TMPC}.1"
	if ! grep -q "video=HDMI-A-1:${W}x${H}" "${TMPC}.1"; then
		sed "s/^/video=HDMI-A-1:${W}x${H}@${R}D /" "${TMPC}.1" > "${TMPC}.2"
	else
		cp "${TMPC}.1" "${TMPC}.2"
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

# Touch: USB HID (ElecLab 1280×400 bar and similar).
# - X11/libinput path only when LightDM is used
# - kmsdrm (rk00pi) needs group `input` + udev on /dev/input/event*
# - app maps SDL FINGER* → mouse (see RK-00pi gui/app.py)
install -d "${ROOTFS_DIR}/etc/X11/xorg.conf.d"
install -m 644 files/40-libinput-touch.conf \
	"${ROOTFS_DIR}/etc/X11/xorg.conf.d/40-libinput-touch.conf"
install -d "${ROOTFS_DIR}/etc/udev/rules.d"
install -m 644 files/99-patchbox-touch.rules \
	"${ROOTFS_DIR}/etc/udev/rules.d/99-patchbox-touch.rules"

install -m 755 files/patchbox-display-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-display-status"
install -m 755 files/patchbox-touch-probe \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-touch-probe"
install -m 755 files/patchbox-soak \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-soak"
# On-device soak checklist (also in the image home dir for SSH sessions).
if [ -f "${BASE_DIR}/SOAK-PROFILE-A.md" ]; then
	install -m 644 "${BASE_DIR}/SOAK-PROFILE-A.md" \
		"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/SOAK-PROFILE-A.md"
	install -d "${ROOTFS_DIR}/usr/share/doc/patchbox"
	install -m 644 "${BASE_DIR}/SOAK-PROFILE-A.md" \
		"${ROOTFS_DIR}/usr/share/doc/patchbox/SOAK-PROFILE-A.md"
fi

# Compact LXDE panel height for a short 400px-tall bar
if [ -f "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel" ]; then
	# Best-effort: shrink height if present
	TMPP="$(mktemp)"
	sed -E 's/^height=[0-9]+/height=28/' \
		"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel" > "${TMPP}" || true
	if [ -s "${TMPP}" ]; then
		cat "${TMPP}" > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/.config/lxpanel/LXDE-pi/panels/panel"
	fi
	rm -f "${TMPP}"
fi

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/DISPLAY-PISOUND.txt" <<EOF
Patchbox OS — Pisound + HDMI ${W}x${H} ultrawide
=================================================

Hardware stack
  Raspberry Pi 5
  + Blokas Pisound (40-pin) — 1/4" audio in/out, MIDI DIN in/out
  + HDMI monitor ${W}x${H} + USB touch cable

Display
  config.txt: hdmi_group=2, hdmi_mode=87, hdmi_cvt=${W} ${H} ${R} 6 0 0 0
  cmdline:    video=HDMI-A-1:${W}x${H}@${R}D
  If the panel's EDID already lists ${W}x${H}, modes may still apply as force.
  If picture is wrong: try removing hdmi_ignore_edid= line, or switch HDMI port
  (Pi 5 has two HDMI — plug into HDMI-A-1 nearest USB-C, or edit to HDMI-A-2).

Touch (ElecLab / USB-HID bar panels)
  Hardware needs BOTH cables: HDMI (video) + USB-A (touch controller).
  ElecLab 7.4" 1280×400 uses an onboard Cortex-M4 HID — no vendor driver.
  SDL kmsdrm path (rk00pi): group 'input' + SupplementaryGroups=… input,
  plus the app converts FINGER*→mouse. X11 libinput conf only applies if
  you stop rk00pi and run LightDM.
  Checks:
    patchbox-display-status
    patchbox-touch-probe          # live: tap panel, see events
    lsusb ; cat /proc/bus/input/devices
    ls -l /dev/input/event* ; id rk00pi
  Field repair: sudo patchbox-fix-input-button

Audio / MIDI
  Pisound is the pro I/O device (not onboard HDMI audio for performance work).
  JACK: select Pisound in patchbox-cli / qjackctl.
  aplay -l ; amidi -l ; jack_lsp

Checks
  patchbox-display-status
  sudo patchbox-touch-probe
  sudo patchbox-soak
  cat /boot/firmware/config.txt | grep hdmi_
  cat /boot/firmware/cmdline.txt

Full soak checklist
  ~/SOAK-PROFILE-A.md
  (or /usr/share/doc/patchbox/SOAK-PROFILE-A.md)

Power saving
  LightDM: X -s 0 -dpms (panel stays on)
EOF

chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/DISPLAY-PISOUND.txt" 2>/dev/null || true

# Optional OSK
on_chroot << 'EOF' || true
	apt-get install -y squeekboard 2>/dev/null || apt-get install -y matchbox-keyboard 2>/dev/null || true
EOF

echo "HDMI ultrawide: ${W}x${H}@${R} configured (Pisound-friendly stack)"
