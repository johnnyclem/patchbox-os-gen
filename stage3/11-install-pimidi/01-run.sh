#!/bin/bash -e
# Blokas Pimidi — 2× TRS MIDI IN + 2× TRS MIDI OUT (Type A).
# Product path when Pisound is off the header (Pi 5 + HDMI bar + RK-00pi).
#
# ENABLE_PIMIDI=1 (default when set in config) installs packages, writes
# dtoverlay=pimidi,sel=N, and points the appliance hub at seq ports a/b.

if [ "${ENABLE_PIMIDI}" != "1" ]; then
	echo "ENABLE_PIMIDI!=1 — skipping Pimidi stage"
	exit 0
fi

SEL="${PIMIDI_SEL:-0}"
CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
if [ ! -f "${CONFIG_TXT}" ]; then
	echo "ERROR: ${CONFIG_TXT} missing"
	exit 1
fi

echo "Pimidi: sel=${SEL} → ${CONFIG_TXT}"

# Full-DPI panels own the 40-pin. Writing pimidi + i2c_arm can black the glass
# or kill touch. Skip the DT overlay unless the profile opts in with KEEP.
SKIP_PIMIDI_DT=0
if [ "${ENABLE_HYPERPIXEL4}" = "1" ] && [ "${HYPERPIXEL_KEEP_PIMIDI:-0}" != "1" ]; then
	SKIP_PIMIDI_DT=1
	echo "  ENABLE_HYPERPIXEL4=1 — installing packages only (no pimidi DT overlay)."
	echo "  TRS MIDI needs Profile A (HDMI) or USB MIDI on the HyperPixel stack."
fi
if [ "${ENABLE_WAVESHARE_DPI}" = "1" ] && [ "${WAVESHARE_KEEP_PIMIDI:-0}" != "1" ]; then
	SKIP_PIMIDI_DT=1
	echo "  ENABLE_WAVESHARE_DPI=1 — installing packages only (no pimidi DT overlay)."
	echo "  Stack with WAVESHARE_KEEP_PIMIDI=1 is experimental; else use USB MIDI."
fi
if [ "${SKIP_PIMIDI_DT}" = "1" ]; then
	:
else
	# Strip prior managed Pimidi / i2c baudrate lines we own
	TMP="$(mktemp)"
	while IFS= read -r line || [ -n "${line}" ]; do
		s="${line#"${line%%[![:space:]]*}"}"
		case "${s}" in
			dtoverlay=pimidi*|*'--- Pimidi'*|*'--- end Pimidi'*)
				continue ;;
			dtparam=i2c_arm=on,i2c_arm_baudrate=*)
				# Only drop the high-rate line we write; leave generic i2c alone.
				continue ;;
		esac
		printf '%s\n' "${line}"
	done < "${CONFIG_TXT}" > "${TMP}"

	# Ensure i2c-dev module loads
	if [ -f "${ROOTFS_DIR}/etc/modules" ]; then
		if ! grep -qE '^i2c-dev' "${ROOTFS_DIR}/etc/modules"; then
			echo "i2c-dev" >> "${ROOTFS_DIR}/etc/modules"
		fi
	fi

	cat >> "${TMP}" <<EOF

# --- Pimidi 2x2 TRS MIDI (sel=${SEL}) ---
# See https://blokas.io/pimidi/docs/advanced-configuration/
dtparam=i2c_arm=on,i2c_arm_baudrate=1000000
dtoverlay=pimidi,sel=${SEL}
# --- end Pimidi ---
EOF

	cat "${TMP}" > "${CONFIG_TXT}"
	rm -f "${TMP}"
	echo "  wrote dtoverlay=pimidi,sel=${SEL}"
fi

# Status helper
install -d "${ROOTFS_DIR}/usr/local/bin"
install -m 755 files/patchbox-pimidi-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-pimidi-status"

# Appliance notes (panel line follows active display profile)
if [ "${ENABLE_WAVESHARE_DPI}" = "1" ]; then
	_PANEL_NOTE="Waveshare 3.5 DPI ${WAVESHARE_WIDTH:-640}×${WAVESHARE_HEIGHT:-480} (keep_pimidi=${WAVESHARE_KEEP_PIMIDI:-0})"
elif [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	_PANEL_NOTE="HyperPixel 4 ${HYPERPIXEL_WIDTH:-800}×${HYPERPIXEL_HEIGHT:-480} (keep_pimidi=${HYPERPIXEL_KEEP_PIMIDI:-0})"
else
	_PANEL_NOTE="HDMI ${HDMI_WIDTH:-1280}×${HDMI_HEIGHT:-400} + USB touch (ElecLab)"
fi
if [ "${SKIP_PIMIDI_DT}" = "1" ]; then
	_DT_NOTE="packages only — dtoverlay=pimidi NOT written (DPI owns header)"
else
	_DT_NOTE="dtoverlay=pimidi,sel=${SEL} + i2c_arm_baudrate=1000000"
fi

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/PIMIDI.txt" <<EOF
Patchbox OS — Pimidi 2×2 + RK-00pi
==================================

Hardware
  Raspberry Pi 5
  + Blokas Pimidi (40-pin), sel=${SEL}
      TRS MIDI: A in/out, B in/out (Type A)
  + ${_PANEL_NOTE}
  + RK-00pi kiosk (no Pisound — no The Button / no tape PCM)

Software
  ${_DT_NOTE}
  package: pimidi (snd_pimidi)

ALSA names (sel=0)
  client  pimidi0
  seq ports   a  (TRS jack A, BOTH)
              b  (TRS jack B, BOTH)
  amidi may list hw as pimidi0-a / pimidi0-b — the hub matches seq names.

RK-00pi hub
  Factory preset: pimidi-2x2.rkhub
  Endpoints: din_in_a/b, din_out_a/b, seq, rec
  Starter project loads this hub so ports bind on boot.

Checks
  patchbox-pimidi-status
  amidi -l
  aconnect -l
  lsmod | grep snd_pimidi

Stack / sel
  One board: sel=0 (default). Additional boards need unique sel=1..3
  and another dtoverlay=pimidi,sel=N line (re-run install or edit config.txt).

DPI + Pimidi
  Full-GPIO panels (HyperPixel / Waveshare) can fight pimidi pinmux.
  Profile C (Waveshare) sets WAVESHARE_KEEP_PIMIDI=1 experimentally.
  If the glass stays black or touch dies, rebuild with KEEP=0 and use USB MIDI,
  or use Profile A (HDMI + Pimidi) for a conflict-free TRS stack.
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/PIMIDI.txt" 2>/dev/null || true

echo "Pimidi stage done (sel=${SEL})"
