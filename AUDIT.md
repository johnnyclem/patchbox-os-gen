# Patchbox OS gen — Red-team & Audio/MIDI Latency Audit

Scope: `patchbox-os-gen`, a pi-gen fork (Debian bookworm) that builds Patchbox
OS, a Raspberry Pi audio/MIDI appliance distro (JACK2, Pisound, Pure Data,
SuperCollider, Sonic Pi, Pianoteq). This document summarizes findings and
what was changed. See the README's "Patchbox OS: audio/MIDI latency &
security tuning" section for the user-facing config-variable reference.

## Summary of changes

| Area | Fixed by default | Parameterized (opt-in/opt-out) | Documented, not changed |
|---|---|---|---|
| Kernel cmdline / boot tuning | `threadirqs`, `audit=0`, `usbcore.autosuspend=-1`, `disable_splash`, `initial_turbo` | `force_turbo` (commented), RT kernel via `RT_KERNEL_VERSION` | `isolcpus`/`nohz_full` (manual) |
| Realtime limits | `/etc/security/limits.d/95-patchbox-audio.conf` | — | — |
| sysctl | `vm.swappiness`, dirty ratios | — | swap size (`CONF_SWAPSIZE`) |
| CPU governor | fixed to cover all cpufreq policies | — | — |
| IRQ priority | boot-time priority bump for existing audio/USB IRQ threads | — | hot-plug re-prioritization (manual) |
| Build robustness | shebangs/`set -e`, quoting, pinned pisound checkout | `PISOUND_GIT_REF` | — |
| Root password | transient `root:root` removed | — | — |
| Apt transport | blokas.io + archive.raspberrypi.com moved to HTTPS | — | raspbian.raspberrypi.com stays HTTP (no working HTTPS endpoint) |
| Background services | — | `ENABLE_VNC`, `ENABLE_TELEMETRY`, `ENABLE_WIFI_HOTSPOT` (all default **on**, unchanged) | — |
| Credentials | — | `HOTSPOT_PASSPHRASE`, `ENABLE_FIRST_LOGIN_PASSWORD_CHANGE` (default **on**) | default `patch`/`blokaslabs`, passwordless sudo, `Xwrapper allowed_users=anybody`, user-rename SKIP |

## Corrections to initial findings

Two things surfaced by an early pass turned out to be inaccurate once
traced through the actual code paths — noted here so they aren't repeated:

1. **"Shipped root password is `root`" — overstated.** `stage1/01-sys-tweaks/00-run.sh`
   did set `root:root` mid-build, but `export-image/05-finalise/01-run.sh`
   already runs `usermod --pass='*' root` inside `on_chroot`, which locks
   root again before the final image is produced. `stage3/EXPORT_IMAGE`
   exists and no stage carries a `SKIP` file, so finalise always runs for
   the real build. The exposure was real but narrow: an *intermediate*
   rootfs (inspected mid-build, or a build aborted before finalise) carried
   a known root password. The `root:root` line has been removed since it
   served no purpose (finalise already locks root) and closes that window
   entirely.

2. **"SSH enabled by default" — actually a latent bug making it disabled.**
   `stage3/01-misc-config/00-run.sh` did `touch ${ROOTFS_DIR}/boot/ssh`,
   intending to drop the boot-partition marker file that Raspberry Pi OS's
   `sshswitch.service` looks for. But on bookworm, `/boot/firmware` (the
   FAT partition, per `stage1/01-sys-tweaks/files/fstab`) is a *separate
   mount point* from `/boot` (an ext4 directory on the rootfs containing
   only symlinks to `firmware/...`). The `touch` created a plain file at
   `${ROOTFS_DIR}/boot/ssh` — the wrong filesystem — which `sshswitch`
   never looks at. Meanwhile `ENABLE_SSH` (the actual supported mechanism,
   used by `stage2/01-sys-tweaks/01-run.sh`) defaults to `0` and is unset
   in `config`, so `systemctl disable ssh` runs. **Net effect: SSH almost
   certainly ships disabled**, not enabled, contradicting the initial
   report and likely breaking the documented headless (hotspot + SSH)
   onboarding flow. Fixed by deleting the broken `touch` and setting
   `ENABLE_SSH=1` in `config`, which routes through the real mechanism.

A related, previously unreported bug of the same class was found and fixed
while auditing this area: `stage3/04-install-sw/08-run.sh` used `sed -i` on
`${ROOTFS_DIR}/boot/config.txt`. Since that path is a symlink to
`firmware/config.txt`, `sed -i` replaces the *symlink itself* with a
regular file containing the edited content, leaving the real,
runtime-mounted `firmware/config.txt` untouched — so the intended
1280×720 HDMI defaults likely never applied. Fixed by editing
`${ROOTFS_DIR}/boot/firmware/config.txt` directly.

## Findings addressed

**Latency / audio-MIDI (Tier 1)**
- Stock `cmdline.txt` had no `threadirqs` — added, along with `audit=0` and
  `usbcore.autosuspend=-1` (USB audio/MIDI interfaces were subject to
  autosuspend, a dropout/wake-latency source).
- No explicit `rtprio`/`memlock` limits file — the realtime story rested
  entirely on jackd2's debconf-driven postinst. Added an explicit,
  in-repo `/etc/security/limits.d/95-patchbox-audio.conf`.
- CPU governor service wrote `performance` to `cpu0` only
  (`scaling_governor` under a shared cpufreq policy usually covers all
  cores on Pi hardware, but the unit was fragile against topology
  differences) — rewritten to loop over every `cpufreq/policy*`.
- No sysctl tuning at all — added `vm.swappiness=10` and reduced
  dirty-writeback ratios to cut paging/writeback jitter. Swap itself stays
  on (100 MB) as an OOM safety net for 512 MB boards; documented how to
  disable it.
- No IRQ prioritization — added a boot-time pass that raises the realtime
  priority of audio/USB IRQ kernel threads (pairs with `threadirqs`).
  Limitation, documented in the README: this only catches IRQ threads that
  exist at boot; a hot-plugged USB interface's IRQ thread isn't
  automatically re-prioritized.
- PREEMPT_RT kernel was referenced by a dead, commented-out package name
  for a pre-bookworm release. Removed the dead reference; added an opt-in
  scaffold (`stage3/05-rt-kernel`, gated on `RT_KERNEL_VERSION`) so a real
  package name can be dropped in later without further plumbing changes.
- `config.txt` had no boot-time tuning — added `disable_splash=1` and
  `initial_turbo=60`; `force_turbo=1` is present but commented out
  (heat/power tradeoff, opt-in).

**Build robustness (Tier 2)**
- ~9 stage3 scripts had no shebang/`set -e`, so host-side failures
  (`install`, `cp`, `sed`) were silently swallowed by `build.sh`'s direct
  `./NN-run.sh` invocation (the parent's `-e` doesn't propagate across
  process boundaries). All now start with `#!/bin/bash -e`.
- Unquoted `${ROOTFS_DIR}`/`${FIRST_USER_NAME}`/`$HOSTNAME` throughout
  stage3 — quoted. Harmless under the current no-space `WORK_DIR`/`IMG_NAME`
  defaults, but fragile.
- `stage3/04-install-sw/08-run.sh` hardcoded the username `patch` instead
  of `${FIRST_USER_NAME}` in a few paths — fixed for consistency with the
  rest of the codebase (also relevant if `FIRST_USER_NAME` is ever
  customized).
- Unpinned `git fetch && git checkout patchbox` inside the pisound stage —
  now `git checkout "${PISOUND_GIT_REF}"`, defaulting to the same branch
  name (identical attached-branch behavior) but overridable to a tag/SHA
  for reproducible builds (git checkout naturally detaches HEAD for a
  SHA/tag, so no explicit `--detach` is needed or used, keeping the
  default case byte-for-byte the same as before).

**Security (Tier 3)**
- Transient `root:root` password removed (see corrections above).
- `chmod -R 777 /usr/local/puredata-patches` (world-writable) replaced
  with owner/`audio`-group-writable permissions — same practical UX for
  `patch` and any `audio`-group member, no world-writable executables.
- `apt.blokas.io` and `archive.raspberrypi.com` moved to HTTPS (both
  verified live during this pass); `raspbian.raspberrypi.com` stays HTTP —
  no working HTTPS endpoint was found for it at audit time, and GPG
  signature verification (via debootstrap's `--keyring`) still protects
  package integrity either way.
- Deliberate product-UX defaults — default `patch`/`blokaslabs`
  credentials with first-boot rename disabled
  (`export-image/01-user-rename/SKIP`), passwordless sudo for `patch`,
  and `Xwrapper allowed_users=anybody` (to allow `startx` over SSH) — were
  **not** changed, per product intent, but are now easier to harden:
  `ENABLE_FIRST_LOGIN_PASSWORD_CHANGE=1` (new default) forces a password
  change at first login; `HOTSPOT_PASSPHRASE`, `ENABLE_VNC`,
  `ENABLE_TELEMETRY`, and `ENABLE_WIFI_HOTSPOT` are now build-time
  variables instead of hardcoded; `PUBKEY_ONLY_SSH` (pre-existing
  upstream feature) disables SSH password auth entirely.

## Known limitations / follow-ups not addressed in this pass

- `blokas-telemetry`'s systemd unit name is assumed to be
  `blokas-telemetry` in `stage3/04-install-sw/02-run.sh`'s
  `ENABLE_TELEMETRY=0` branch; this is unverified against the actual
  package (no way to inspect it without a working chroot/apt access in
  this environment) and is guarded with `|| true` so a wrong name fails
  soft instead of breaking the build. Verify on the next real build.
- `rtirq-init`-style per-device IRQ priority tuning (distinct priorities
  per device class, matching `/proc/interrupts` names precisely) was
  considered but not used, since package availability for bookworm
  couldn't be verified in this environment (no apt/network access to the
  target repos). A self-contained systemd unit + shell script was used
  instead, matching audio/USB IRQ thread names by pattern.
- Full end-to-end image build was not run (no Docker/loop-device access in
  this environment); verification was limited to `bash -n` syntax checks
  on every modified/existing shell script (all pass), executable-bit
  checks, and manual review of the systemd unit files' `$$`-escaping and
  `ConditionPathExistsGlob` guards. Recommend a full `./build-docker.sh`
  (or `STAGE_LIST="stage0 stage1"` partial) run before shipping, plus a
  real Pi boot test for the cmdline/sysctl/governor/IRQ changes.
- `isolcpus`/`nohz_full` CPU isolation, and the RT kernel, remain
  documented opt-ins rather than defaults — see README for the tradeoffs.
