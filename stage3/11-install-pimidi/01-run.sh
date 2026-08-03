#!/bin/bash -e
# Blokas Pimidi — 2× TRS MIDI IN + 2× TRS MIDI OUT (Type A).
# Product path when Pisound is off the header (Pi 5 + HDMI bar + RK-00pi).
#
# ENABLE_PIMIDI=1 (default when set in config) installs packages, writes
# dtoverlay=pimidi,sel=N, and points the appliance hub at pimidi-a/b.

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

# HyperPixel (and other full-DPI panels) own the 40-pin. Writing pimidi +
# i2c_arm here would black the panel. Stage 12 also strips these; skip early
# when the HyperPixel profile is active unless explicitly overridden.
if [ "${ENABLE_HYPERPIXEL4}" = "1" ] && [ "${HYPERPIXEL_KEEP_PIMIDI:-0}" != "1" ]; then
	echo "  ENABLE_HYPERPIXEL4=1 — installing packages only (no pimidi DT overlay)."
	echo "  TRS MIDI needs Profile A (HDMI) or USB MIDI on the HyperPixel stack."
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

# Appliance notes
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/PIMIDI.txt" <<EOF
Patchbox OS — Pimidi 2×2 + RK-00pi
==================================

Hardware
  Raspberry Pi 5
  + Blokas Pimidi (40-pin), sel=${SEL}
      TRS MIDI: A in/out, B in/out (Type A)
  + HDMI 1280×400 + USB touch (ElecLab)
  + RK-00pi kiosk (no Pisound — no The Button / no tape PCM)

Software
  dtoverlay=pimidi,sel=${SEL}
  dtparam=i2c_arm=on,i2c_arm_baudrate=1000000
  package: pimidi (snd_pimidi)

ALSA names (sel=0)
  client  pimidi0
  ports   pimidi-a  (TRS jack A, BOTH)
          pimidi-b  (TRS jack B, BOTH)

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
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/PIMIDI.txt" 2>/dev/null || true

echo "Pimidi stage done (sel=${SEL})"
