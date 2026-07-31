#!/bin/bash -e
# RaspiAudio Mic Ultra++ / Mic+ (I2S) under Inky Impression.
#
# Gated on ENABLE_RASPIAUDIO (default 1 for this appliance build).
# Stack order: Pi 5 → RaspiAudio (passthrough header) → Inky on top.
#
# Pimidi (Blokas TRS MIDI) is deferred until hardware arrives — do not
# enable pimidi overlays here yet.

if [ "${ENABLE_RASPIAUDIO}" != "1" ]; then
	echo "ENABLE_RASPIAUDIO!=1 — skipping RaspiAudio setup"
	exit 0
fi

OVERLAY="${RASPIAUDIO_OVERLAY:-googlevoicehat-soundcard}"
case "${OVERLAY}" in
	googlevoicehat-soundcard|wm8960-soundcard) ;;
	*)
		echo "Unknown RASPIAUDIO_OVERLAY=${OVERLAY}; using googlevoicehat-soundcard"
		OVERLAY="googlevoicehat-soundcard"
		;;
esac

CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"

# Primary I2S card: enable chosen overlay; disable onboard bcm audio so
# ALSA/JACK don't prefer the HDMI/analogue sink by default.
if [ -f "${CONFIG_TXT}" ]; then
	# Ensure i2s is on (also set in stage1 template for new builds).
	if ! grep -qE '^dtparam=i2s=on' "${CONFIG_TXT}"; then
		sed -i 's/^#dtparam=i2s=on/dtparam=i2s=on/' "${CONFIG_TXT}" || true
		if ! grep -qE '^dtparam=i2s=on' "${CONFIG_TXT}"; then
			echo "dtparam=i2s=on" >> "${CONFIG_TXT}"
		fi
	fi

	# Turn off onboard audio device.
	sed -i 's/^dtparam=audio=on/#dtparam=audio=on  # disabled: RaspiAudio is primary/' "${CONFIG_TXT}"

	# Drop any previous raspiaudio overlay lines we manage, then append.
	sed -i \
		-e '/^dtoverlay=googlevoicehat-soundcard/d' \
		-e '/^dtoverlay=wm8960-soundcard/d' \
		-e '/^#dtoverlay=googlevoicehat-soundcard/d' \
		"${CONFIG_TXT}"

	{
		echo ""
		echo "# --- RaspiAudio (ENABLE_RASPIAUDIO=1) ---"
		echo "# Overlay: ${OVERLAY}"
		echo "# googlevoicehat-soundcard = Method 1 (Mic+ / simple Ultra++)"
		echo "# wm8960-soundcard         = Method 2 full WM8960 mixer (Ultra++)"
		echo "dtoverlay=${OVERLAY}"
	} >> "${CONFIG_TXT}"
fi

# ALSA defaults: prefer the I2S card name patterns used by the overlays.
install -d "${ROOTFS_DIR}/etc/alsa/conf.d"
install -m 644 files/99-raspiaudio.conf \
	"${ROOTFS_DIR}/etc/alsa/conf.d/99-raspiaudio.conf"

# Helper for the appliance user.
install -m 755 files/patchbox-raspiaudio-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-raspiaudio-status"

# JACK device hint (patchbox-cli / manual jackd). Card index varies; name is stable.
install -d "${ROOTFS_DIR}/etc/patchbox"
cat > "${ROOTFS_DIR}/etc/patchbox/raspiaudio.env" <<EOF
# Sourced by helpers; also useful when starting jackd manually.
# Prefer the ALSA name over hw:N (N can shift with HDMI/USB).
# Card name after first boot (aplay -l). Common values:
#   googlevoicehat-soundcard → often "sndrpigooglevoi" / "VoiceHAT"
#   wm8960-soundcard         → often "wm8960soundcard"
PATCHBOX_ALSA_CARD="${RASPIAUDIO_ALSA_NAME:-wm8960soundcard}"
RASPIAUDIO_OVERLAY=${OVERLAY}
EOF

install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/RASPIAUDIO-INKY.txt" <<EOF
Patchbox OS — RaspiAudio + Inky Impression stack
================================================

Hardware order (power off when assembling)
  1. Raspberry Pi 5
  2. RaspiAudio Mic Ultra++ (or Mic+) with 40-pin passthrough / stacking header
  3. Pimoroni Inky Impression 5.7" on top (booster header + standoffs)

Buses
  RaspiAudio : I2S (GPIO 18–21) + I2C codec control
  Inky       : SPI0 + I2C EEPROM + panel GPIOs + buttons A/B/C/D
  These do not share the same data lines for the core audio path.

Overlay active at build time
  dtoverlay=${OVERLAY}
  Onboard dtparam=audio is disabled so the I2S card is primary.

If Ultra++ has no sound after flash
  1. aplay -l   /   arecord -l
  2. Try the other overlay in /boot/firmware/config.txt:
       dtoverlay=wm8960-soundcard
     or
       dtoverlay=googlevoicehat-soundcard
  3. sudo reboot
  4. alsamixer  (F6 select card; unmute Speaker/Headphone/Mic)

JACK
  patchbox module jack  — select the RaspiAudio / voicehat / wm8960 device
  or manually:
    jackd -d alsa -d hw:CARD=<name_from_aplay> -r 48000 -p 128

Inky UI (unchanged)
  patchbox-inky-ui
  Buttons A/B/C/D drive the patchbay (not RaspiAudio).

Deferred: Blokas Pimidi (2×2 MIDI TRS Type A)
  Ordered separately; will stack with sel=0 (GPIO23) when hardware arrives.
  Do not enable dtoverlay=pimidi until then.

Check
  patchbox-raspiaudio-status
EOF

chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni" \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/RASPIAUDIO-INKY.txt" \
	2>/dev/null || true

echo "RaspiAudio stage: overlay=${OVERLAY}"
