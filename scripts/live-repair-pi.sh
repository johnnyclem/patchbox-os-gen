#!/usr/bin/env bash
# live-repair-pi.sh — unstick dead touch + The Button on a running Patchbox Pi.
#
# Why the earlier group-only fix was not enough
# ---------------------------------------------
# The baked image often ships an older /opt/rk00pi that:
#   • has no gui/touch.py (native FINGER→mouse path)
#   • has no SupplementaryGroups=input on the unit
#   • may not have button scripts mapped in /etc/pisound.conf
# USB being plugged in does not matter until the service user can open
# /dev/input/event* AND the app translates FINGER events to mouse.
#
# This script rsyncs the full RK-00pi app tree from your laptop (keeps the
# on-device venv + projects), installs unit/udev/button wiring, restarts,
# and prints touch_doctor + diag.
#
# Usage (from patchbox-os-gen checkout):
#   ./scripts/live-repair-pi.sh
#   ./scripts/live-repair-pi.sh patch@192.168.50.190
#   ./scripts/live-repair-pi.sh --diag-only
#
# You will be prompted for the patch password (and sudo on the Pi).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${HOST:-patch@patchbox.local}"
DIAG_ONLY=0
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
	case "$1" in
		--diag-only) DIAG_ONLY=1; shift ;;
		--host) HOST=$2; shift 2 ;;
		-h|--help)
			sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*@*|*patchbox*|[0-9]*)
			if [[ "$1" == *@* ]]; then HOST=$1; else HOST="patch@$1"; fi
			shift
			;;
		*) die "unknown arg: $1" ;;
	esac
done

[ -d "$ROOT/RK-00pi/gui" ] || die "missing RK-00pi/ — run from patchbox-os-gen"
[ -f "$ROOT/RK-00pi/gui/touch.py" ] || die "missing gui/touch.py"
[ -f "$ROOT/RK-00pi/main.py" ] || die "missing RK-00pi/main.py"
grep -qE '<<<<<<|>>>>>>' "$ROOT/RK-00pi/deploy/rk00pi.service" 2>/dev/null && \
	die "rk00pi.service has merge conflict markers — fix before deploy"
python3 -c "import ast; ast.parse(open('$ROOT/RK-00pi/gui/app.py').read())" || \
	die "gui/app.py is not valid Python"
python3 -c "import ast; ast.parse(open('$ROOT/RK-00pi/gui/touch.py').read())" || \
	die "gui/touch.py is not valid Python"

say "target: $HOST"
say "testing SSH…"
ssh "${SSH_OPTS[@]}" "$HOST" 'echo "  connected as $(whoami)@$(hostname)"; uname -a' || \
	die "SSH failed — use interactive ssh once if password change is forced"

REMOTE_DIR=/tmp/patchbox-live-repair-$$
say "staging on Pi at $REMOTE_DIR"
ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p '$REMOTE_DIR'/{tree,pisound,helpers}"

say "rsync full RK-00pi tree (excludes venv, .git, projects, caches)…"
# Prefer rsync; fall back to tar over ssh if rsync missing on either side.
if command -v rsync >/dev/null 2>&1; then
	rsync -az --delete \
		--exclude '.git/' \
		--exclude '.github/' \
		--exclude 'venv/' \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		--exclude '.pytest_cache/' \
		--exclude 'data/projects/' \
		--exclude 'data/autosave/' \
		-e "ssh ${SSH_OPTS[*]}" \
		"$ROOT/RK-00pi/" "$HOST:$REMOTE_DIR/tree/"
else
	warn "no local rsync — using tar"
	tar -C "$ROOT/RK-00pi" \
		--exclude '.git' --exclude 'venv' --exclude '__pycache__' \
		--exclude 'data/projects' --exclude '.pytest_cache' \
		-czf - . | ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p '$REMOTE_DIR/tree' && tar -C '$REMOTE_DIR/tree' -xzf -"
fi

scp "${SSH_OPTS[@]}" \
	"$ROOT/RK-00pi/deploy/rk00pi.service" \
	"$HOST:$REMOTE_DIR/rk00pi.service"
scp "${SSH_OPTS[@]}" \
	"$ROOT/RK-00pi/deploy/pisound/"* \
	"$HOST:$REMOTE_DIR/pisound/"
scp "${SSH_OPTS[@]}" \
	"$ROOT/stage3/10-install-rk00pi/files/patchbox-fix-input-button" \
	"$ROOT/stage3/10-install-rk00pi/files/patchbox-diag-input-button" \
	"$HOST:$REMOTE_DIR/helpers/"

if [ "$DIAG_ONLY" -eq 1 ]; then
	say "diag-only"
	ssh -t "${SSH_OPTS[@]}" "$HOST" "sudo bash '$REMOTE_DIR/helpers/patchbox-diag-input-button'"
	exit 0
fi

say "installing on Pi (sudo)…"
ssh -t "${SSH_OPTS[@]}" "$HOST" "sudo bash -s -- '$REMOTE_DIR'" <<'REMOTE'
set -euo pipefail
SRC=${1:?}
APP_USER=rk00pi
PREFIX=/opt/rk00pi
PISOUND_SCRIPTS=/usr/local/pisound/scripts/pisound-btn

echo "==> sync app tree → $PREFIX (preserve venv + projects)"
if [ ! -d "$PREFIX" ]; then
	echo "!! $PREFIX missing — creating"
	mkdir -p "$PREFIX"
fi
# Keep live data + venv
if command -v rsync >/dev/null 2>&1; then
	rsync -a \
		--exclude 'venv/' \
		--exclude 'data/projects/' \
		--exclude 'data/autosave/' \
		"$SRC/tree/" "$PREFIX/"
else
	# tar merge without deleting venv
	tar -C "$SRC/tree" -cf - . | tar -C "$PREFIX" -xf -
fi
# Ensure data dirs exist
mkdir -p "$PREFIX/data" 2>/dev/null || true
mkdir -p /var/lib/rk00pi/{projects,presets,maps,autosave}
if id "$APP_USER" >/dev/null 2>&1; then
	chown -R "$APP_USER:$APP_USER" "$PREFIX" 2>/dev/null || true
	# do not chown away system paths if data is elsewhere
	chown -R "$APP_USER:$APP_USER" /var/lib/rk00pi 2>/dev/null || true
fi
rm -rf "$PREFIX"/gui/__pycache__ "$PREFIX"/gui/screens/__pycache__ \
	"$PREFIX"/core/__pycache__ "$PREFIX"/bench/__pycache__ 2>/dev/null || true
test -f "$PREFIX/gui/touch.py" && echo "    gui/touch.py OK"
test -f "$PREFIX/gui/app.py" && echo "    gui/app.py OK"
test -f "$PREFIX/main.py" && echo "    main.py OK"

echo "==> unit + drop-in"
install -d /etc/systemd/system/rk00pi.service.d
install -m 644 "$SRC/rk00pi.service" /etc/systemd/system/rk00pi.service
cat > /etc/systemd/system/rk00pi.service.d/10-input-button.conf <<'EOF'
[Service]
SupplementaryGroups=audio gpio video render input
RuntimeDirectory=rk00pi
RuntimeDirectoryMode=0755
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_TOUCH_MOUSE_EVENTS=0
Environment=SDL_MOUSE_TOUCH_EVENTS=0
EOF

echo "==> groups for $APP_USER"
if id "$APP_USER" >/dev/null 2>&1; then
	usermod -aG input,audio,gpio,video,render "$APP_USER" 2>/dev/null || \
		usermod -aG input "$APP_USER" || true
	echo "    $(id -nG "$APP_USER")"
else
	echo "!! no user $APP_USER"
fi

echo "==> udev (all evdev nodes → group input, mode 0660)"
cat > /etc/udev/rules.d/99-patchbox-touch.rules <<'UDEV'
# Appliance: SDL/kmsdrm needs group-read on every event node.
KERNEL=="event*", SUBSYSTEM=="input", MODE="0660", GROUP="input"
KERNEL=="mice",    SUBSYSTEM=="input", MODE="0660", GROUP="input"
KERNEL=="mouse*",  SUBSYSTEM=="input", MODE="0660", GROUP="input"
UDEV
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=input 2>/dev/null || true
# Force mode now (trigger is best-effort)
for n in /dev/input/event*; do
	[ -e "$n" ] || continue
	chgrp input "$n" 2>/dev/null || true
	chmod 660 "$n" 2>/dev/null || true
done

echo "==> The Button bridge"
install -d /usr/local/bin "$PISOUND_SCRIPTS"
install -m 755 "$SRC/pisound/rk00pi-btn" /usr/local/bin/rk00pi-btn
install -m 755 "$SRC/pisound"/rk00pi_*.sh "$PISOUND_SCRIPTS/"
install -d /usr/local/sbin /usr/local/bin
install -m 755 "$SRC/helpers/patchbox-fix-input-button" /usr/local/sbin/patchbox-fix-input-button
install -m 755 "$SRC/helpers/patchbox-diag-input-button" /usr/local/bin/patchbox-diag-input-button

CONF=/etc/pisound.conf
[ -f "$CONF" ] || touch "$CONF"
if [ -s "$CONF" ] && [ ! -f /etc/pisound.conf.rk00pi.bak ]; then
	cp "$CONF" /etc/pisound.conf.rk00pi.bak
fi
set_action() {
	local a=$1 s=$2
	if grep -qE "^${a}[[:space:]]" "$CONF"; then
		sed -i "s|^${a}[[:space:]].*|${a} ${s}|" "$CONF"
	else
		printf '%s %s\n' "$a" "$s" >> "$CONF"
	fi
}
for a in CLICK_1 CLICK_2 CLICK_3 CLICK_OTHER; do
	set_action "$a" "$PISOUND_SCRIPTS/rk00pi_click.sh"
done
for a in HOLD_1S HOLD_3S HOLD_5S HOLD_OTHER; do
	set_action "$a" "$PISOUND_SCRIPTS/rk00pi_hold.sh"
done
echo "    mapped CLICK_*/HOLD_* in $CONF"

echo "==> enable + restart services"
systemctl daemon-reload
systemctl enable pisound-btn.service 2>/dev/null || true
systemctl enable rk00pi.service 2>/dev/null || true
systemctl restart pisound-btn.service 2>/dev/null || echo "!! pisound-btn restart failed"
systemctl restart rk00pi.service 2>/dev/null || echo "!! rk00pi restart failed"
sleep 4

echo
echo "========== service status =========="
systemctl --no-pager -l status rk00pi.service 2>/dev/null | head -20 || true
systemctl --no-pager -l status pisound-btn.service 2>/dev/null | head -12 || true

echo
echo "========== TOUCH DOCTOR =========="
if [ -x "$PREFIX/venv/bin/python" ] && [ -f "$PREFIX/bench/touch_doctor.py" ]; then
	(cd "$PREFIX" && sudo -u "$APP_USER" venv/bin/python -m bench.touch_doctor) || true
else
	echo "(skipped — no venv or touch_doctor)"
fi

echo
echo "========== DIAG =========="
bash "$SRC/helpers/patchbox-diag-input-button" || true

echo
echo "========== QUICK TESTS =========="
if [ -S /run/rk00pi/button.sock ]; then
	echo -n "PING: "; /usr/local/bin/rk00pi-btn PING 2>&1 || true
	echo -n "ACTION play_stop: "; /usr/local/bin/rk00pi-btn ACTION play_stop 2>&1 || true
else
	echo "NO /run/rk00pi/button.sock"
fi
echo
echo "journal (errors / touch / button):"
journalctl -u rk00pi -u pisound-btn -b --no-pager 2>/dev/null \
	| grep -iE 'touch|button|input|error|traceback|listening|FAIL|ModuleNotFound' \
	| tail -50 || true
echo
echo "input nodes (as rk00pi can-read?):"
for n in /dev/input/event*; do
	[ -e "$n" ] || continue
	if sudo -u "$APP_USER" test -r "$n" 2>/dev/null; then
		echo "  READ OK  $n  $(ls -l "$n" | awk '{print $1,$3,$4}')"
	else
		echo "  READ NO  $n  $(ls -l "$n" | awk '{print $1,$3,$4}')"
	fi
done
echo
echo "USB:"
lsusb 2>/dev/null | sed 's/^/  /' || true
echo
echo "Done. Tap the panel; single-press The Button."
echo "If STILL dead: paste from TOUCH DOCTOR through USB above."
REMOTE

say "finished"
say "diag again:  ssh $HOST 'sudo patchbox-diag-input-button'"
say "touch doctor: ssh $HOST 'cd /opt/rk00pi && sudo -u rk00pi venv/bin/python -m bench.touch_doctor'"
