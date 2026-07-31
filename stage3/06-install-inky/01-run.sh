#!/bin/bash -e
# Install Pimoroni Inky library + Patchbox splash / patchbay UI.
#
# Gated on ENABLE_INKY (default 1). Set ENABLE_INKY=0 to skip the Python
# venv / services while still leaving SPI+I2C enabled in config.txt.

if [ "${ENABLE_INKY}" != "1" ]; then
	echo "ENABLE_INKY!=1 — skipping Inky Impression software install"
	exit 0
fi

# Kernel modules for userspace I2C/SPI device nodes.
install -d "${ROOTFS_DIR}/etc/modules-load.d"
cat > "${ROOTFS_DIR}/etc/modules-load.d/patchbox-inky.conf" <<'EOF'
i2c-dev
spidev
EOF

# Python package + CLI wrappers.
install -d "${ROOTFS_DIR}/usr/local/lib/patchbox-inky"
cp -a files/patchbox_inky "${ROOTFS_DIR}/usr/local/lib/patchbox-inky/"
# Drop any host __pycache__ that sneaked in.
find "${ROOTFS_DIR}/usr/local/lib/patchbox-inky" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

install -m 755 files/patchbox-inky-ui "${ROOTFS_DIR}/usr/local/bin/patchbox-inky-ui"
install -m 755 files/patchbox-inky-tui "${ROOTFS_DIR}/usr/local/bin/patchbox-inky-tui"
install -m 755 files/patchbox-inky-status "${ROOTFS_DIR}/usr/local/bin/patchbox-inky-status"
install -m 755 files/patchbox-inky-splash "${ROOTFS_DIR}/usr/local/bin/patchbox-inky-splash"
install -m 755 files/patchbox-inky-patchbay "${ROOTFS_DIR}/usr/local/bin/patchbox-inky-patchbay"

# systemd units: substitute the configured first user (default: patch).
install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
for unit in patchbox-inky-ui.service; do
	sed \
		-e "s/^User=patch$/User=${FIRST_USER_NAME}/" \
		-e "s/^Group=patch$/Group=${FIRST_USER_NAME}/" \
		-e "s|Environment=HOME=/home/patch|Environment=HOME=/home/${FIRST_USER_NAME}|" \
		-e "s|WorkingDirectory=/home/patch|WorkingDirectory=/home/${FIRST_USER_NAME}|" \
		-e "s|/home/patch/Pimoroni|/home/${FIRST_USER_NAME}/Pimoroni|g" \
		"files/${unit}" \
		> "${ROOTFS_DIR}/usr/lib/systemd/system/${unit}"
done

# Keep the legacy status oneshot available (disabled) for manual enable.
if [ -f files/patchbox-inky-status.service ]; then
	sed \
		-e "s/^User=patch$/User=${FIRST_USER_NAME}/" \
		-e "s/^Group=patch$/Group=${FIRST_USER_NAME}/" \
		-e "s|Environment=HOME=/home/patch|Environment=HOME=/home/${FIRST_USER_NAME}|" \
		-e "s|WorkingDirectory=/home/patch|WorkingDirectory=/home/${FIRST_USER_NAME}|" \
		files/patchbox-inky-status.service \
		> "${ROOTFS_DIR}/usr/lib/systemd/system/patchbox-inky-status.service"
fi

# System venv with access to apt-provided numpy/pillow/spidev.
on_chroot << EOF
	set -e
	python3 -m venv --system-site-packages /opt/pimoroni
	/opt/pimoroni/bin/pip install --upgrade pip wheel
	PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
		/opt/pimoroni/bin/pip install --no-cache-dir \
			'inky>=2.0.0' 'gpiodevice>=0.0.3' smbus2
	chmod -R a+rX /opt/pimoroni
EOF

# Boot UI service: splash + interactive patchbay. Default ON so the e-paper
# is useful out of the box; set ENABLE_INKY_UI=0 to leave it manual-only.
if [ "${ENABLE_INKY_UI}" = "1" ]; then
	on_chroot << EOF
		systemctl daemon-reload
		systemctl enable patchbox-inky-ui.service
		systemctl disable patchbox-inky-status.service 2>/dev/null || true
EOF
else
	on_chroot << EOF
		systemctl daemon-reload
		systemctl disable patchbox-inky-ui.service 2>/dev/null || true
		systemctl disable patchbox-inky-status.service 2>/dev/null || true
EOF
fi

# Optional legacy status oneshot if someone still sets the old flag alone.
if [ "${ENABLE_INKY_STATUS_SERVICE}" = "1" ] && [ "${ENABLE_INKY_UI}" != "1" ]; then
	on_chroot << EOF
		systemctl enable patchbox-inky-status.service
EOF
fi

# User-facing notes.
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/inky"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/inky/README-patchbox.txt" <<EOF
Patchbox OS — Inky Impression 5.7" UI (600×448, 7-colour)
=========================================================

Hardware
  Pimoroni Inky Impression 5.7" on the 40-pin header.
  Buses: SPI0 (MOSI/MISO/SCK + userspace CS) and I2C1 (SDA/SCL EEPROM).
  Buttons A/B/C/D → BCM GPIO 5 / 6 / 16 / 24.
  Pi 5 overlays: dtoverlay=spi0-0cs, i2c1, i2c1-pi5.

E-ink notes
  7-colour full refresh is ~30s — prefer keyboard TUI for interaction.
  Driver defaults to forced 5.7" UC8159 600x448 (avoids half-screen mis-detect).
  Boot service OFF by default (ENABLE_INKY_UI=0).

  Controls (side buttons + keyboard — not a touch screen):
    A / ↑ k w     move up
    B / ↓ j s     move down
    C / Enter     patch / toggle link
    D / Tab       cycle focus
    r             refresh graph
    q             quit

Commands
  patchbox-inky-tui                 # KEYBOARD patchbay (no e-ink) — preferred
  patchbox-inky-ui clear-test       # full white then black (geometry check)
  patchbox-inky-ui splash --type 5.7
  patchbox-inky-ui ui --type 5.7 --tui
  patchbox-inky-ui --simulate

Python
  venv:    /opt/pimoroni   (source /opt/pimoroni/bin/activate)
  package: /usr/local/lib/patchbox-inky/patchbox_inky

Stack with RaspiAudio (current appliance target)
  Pi 5 → RaspiAudio Mic Ultra++ (passthrough) → Inky on top.
  I2S audio does not use Inky's SPI/button pins. See ~/Pimoroni/RASPIAUDIO-INKY.txt

Deferred: Blokas Pimidi (MIDI TRS) — ordered; enable when boards arrive (sel=0).

Classic Pisound full HAT cannot share the header with Inky (no passthrough).
EOF
chown 1000:1000 \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni" \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/inky" \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/Pimoroni/inky/README-patchbox.txt" \
	2>/dev/null || true
