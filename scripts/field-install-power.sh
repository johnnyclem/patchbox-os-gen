#!/bin/bash
set -euo pipefail
# Run ON the Pi as patch with sudo, after scp'ing the files to /tmp/rk00pi-power/
SRC=${1:-/tmp/rk00pi-power}
sudo install -m 644 "$SRC/diagnostics.py" /opt/rk00pi/gui/screens/diagnostics.py
sudo install -m 644 "$SRC/settings.py" /opt/rk00pi/gui/screens/settings.py
sudo install -m 644 "$SRC/setup.py" /opt/rk00pi/gui/screens/setup.py
sudo install -m 644 "$SRC/app.py" /opt/rk00pi/gui/app.py
sudo install -m 644 "$SRC/main.py" /opt/rk00pi/main.py
sudo install -m 644 "$SRC/button_server.py" /opt/rk00pi/core/button_server.py
sudo install -d /etc/sudoers.d
sudo install -m 440 "$SRC/rk00pi-power" /etc/sudoers.d/rk00pi-power
sudo visudo -cf /etc/sudoers.d/rk00pi-power
sudo systemctl restart rk00pi
sleep 2
systemctl is-active rk00pi
echo "OK — Settings: RESTART (1 tap) / SHUT (2 taps); DIAG: full power strip; I/O banner: RESTART"
