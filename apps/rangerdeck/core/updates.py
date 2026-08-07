"""Launch-time update channel for the Ranger Suite.

The appliance does not keep a full git tree under ``/opt`` (each app is a
frozen install with its own venv). So "is there an update?" cannot be a
local ``git fetch``. Instead:

1. You push the suite to a git remote and bump ``apps/rangers-channel.json``
   (version, commit tip, short notes).
2. On launch the deck fetches that JSON over HTTPS (or falls back to
   ``git ls-remote`` on a configured ref) on a background thread.
3. It compares the remote tip to the local install marker
   (``/var/lib/rangerdeck/installed-channel.json``, falling back to each
   app's ``.patchbox-source-commit`` from the image bake).
4. When they differ the header offers Install; applying is a separate
   privileged script (``patchbox-ranger-update``) that shallow-clones and
   rsyncs sources without touching venvs unless requirements changed.

Network failures are silent (status ``error`` / ``skipped``) — a kiosk on
a dark stage must never hang or nag because Wi‑Fi is down.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

log = logging.getLogger("rangerdeck.updates")

CHANNEL_NAME = "rangers-channel.json"
DEFAULT_CHANNEL_URL = (
    "https://raw.githubusercontent.com/johnnyclem/patchbox-os-gen/"
    "patchbox-2024-01/apps/rangers-channel.json"
)
DEFAULT_GIT_URL = "https://github.com/johnnyclem/patchbox-os-gen.git"
DEFAULT_GIT_REF = "patchbox-2024-01"
DEFAULT_TIMEOUT_S = 4.0
INSTALLED_NAME = "installed-channel.json"
UPDATE_SCRIPT = "/usr/local/sbin/patchbox-ranger-update"

# Status words the GUI switches on.
STATUS_IDLE = "idle"
STATUS_CHECKING = "checking"
STATUS_CURRENT = "current"
STATUS_AVAILABLE = "available"
STATUS_ERROR = "error"
STATUS_DISABLED = "disabled"
STATUS_APPLYING = "applying"


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    version: str = ""
    commit: str = ""
    branch: str = ""
    notes: str = ""
    released: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ChannelInfo":
        raw = raw or {}
        commit = str(raw.get("commit", "") or "").strip().lower()
        # Accept full or short SHAs; compare on the shorter common prefix later.
        return cls(
            version=str(raw.get("version", "") or "").strip(),
            commit=commit,
            branch=str(raw.get("branch", "") or "").strip(),
            notes=str(raw.get("notes", "") or "").strip(),
            released=str(raw.get("released", "") or "").strip(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def short_commit(self) -> str:
        return self.commit[:7] if self.commit else ""


@dataclass(frozen=True, slots=True)
class UpdateSettings:
    enabled: bool = True
    check_on_launch: bool = True
    channel_url: str = DEFAULT_CHANNEL_URL
    git_url: str = DEFAULT_GIT_URL
    git_ref: str = DEFAULT_GIT_REF
    timeout_s: float = DEFAULT_TIMEOUT_S
    auto_apply: bool = False
    # Where the last successfully installed channel is recorded.
    state_dir: Path = Path("/var/lib/rangerdeck")
    # Roots scanned for bake-time .patchbox-source-commit markers.
    opt_root: Path = Path("/opt")


@dataclass
class UpdateState:
    """Mutable snapshot the GUI reads each frame (one lock, tiny fields)."""

    status: str = STATUS_IDLE
    local: ChannelInfo = field(default_factory=ChannelInfo)
    remote: ChannelInfo = field(default_factory=ChannelInfo)
    detail: str = ""            # human one-liner for the panel / journal
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> tuple[str, ChannelInfo, ChannelInfo, str]:
        with self._lock:
            return self.status, self.local, self.remote, self.detail

    def set(self, status: str, *, local: ChannelInfo | None = None,
            remote: ChannelInfo | None = None, detail: str = "") -> None:
        with self._lock:
            self.status = status
            if local is not None:
                self.local = local
            if remote is not None:
                self.remote = remote
            self.detail = detail


def update_settings(config, *, state_dir: Path | None = None) -> UpdateSettings:
    """Read ``[updates]`` from the deck config's ``extra`` table."""
    raw = {}
    if config is not None:
        extra = getattr(config, "extra", None) or {}
        raw = dict(extra.get("updates") or {})
        if state_dir is None:
            paths = getattr(config, "paths", None)
            if paths is not None and getattr(paths, "data_dir", None):
                state_dir = Path(paths.data_dir)
    base = UpdateSettings()
    if state_dir is not None:
        base = UpdateSettings(state_dir=Path(state_dir))
    return UpdateSettings(
        enabled=_bool(raw.get("enabled"), base.enabled),
        check_on_launch=_bool(raw.get("check_on_launch"), base.check_on_launch),
        channel_url=str(raw.get("channel_url", base.channel_url) or base.channel_url),
        git_url=str(raw.get("git_url", base.git_url) or base.git_url),
        git_ref=str(raw.get("git_ref", base.git_ref) or base.git_ref),
        timeout_s=float(raw.get("timeout_s", base.timeout_s) or base.timeout_s),
        auto_apply=_bool(raw.get("auto_apply"), base.auto_apply),
        state_dir=Path(raw["state_dir"]) if raw.get("state_dir") else base.state_dir,
        opt_root=Path(raw["opt_root"]) if raw.get("opt_root") else base.opt_root,
    )


def _bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def commits_match(a: str, b: str) -> bool:
    """True when two SHAs name the same commit (short or full)."""
    a, b = (a or "").lower().strip(), (b or "").lower().strip()
    if not a or not b:
        return False
    n = min(len(a), len(b), 40)
    if n < 7:
        return a == b
    return a[:n] == b[:n]


def read_local_channel(settings: UpdateSettings) -> ChannelInfo:
    """Installed channel, or bake-time commit markers under /opt."""
    marker = settings.state_dir / INSTALLED_NAME
    if marker.is_file():
        try:
            return ChannelInfo.from_dict(
                json.loads(marker.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("installed channel unreadable: %s", exc)
    # Fall back to the bake marker the install stage writes.
    commits: list[str] = []
    root = settings.opt_root
    if root.is_dir():
        for child in sorted(root.iterdir()):
            path = child / ".patchbox-source-commit"
            if path.is_file():
                try:
                    commits.append(path.read_text(encoding="utf-8").strip())
                except OSError:
                    pass
    commit = commits[0] if commits else ""
    # Prefer the majority vote if apps disagree (partial field update).
    if commits:
        tallies: dict[str, int] = {}
        for c in commits:
            key = c[:12]
            tallies[key] = tallies.get(key, 0) + 1
        commit = max(tallies, key=tallies.get)  # type: ignore[arg-type]
        # Restore a full-length sample that matches the winner prefix.
        for c in commits:
            if c.startswith(commit) or commit.startswith(c[:7]):
                commit = c
                break
    return ChannelInfo(commit=commit.lower())


def write_local_channel(settings: UpdateSettings, info: ChannelInfo) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    path = settings.state_dir / INSTALLED_NAME
    path.write_text(json.dumps(info.to_dict(), indent=2) + "\n",
                    encoding="utf-8")


def fetch_channel_json(url: str, timeout: float) -> ChannelInfo:
    """GET the channel JSON. Raises on hard failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RangerDeck-update-check/0.1",
                 "Accept": "application/json"},
        method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return ChannelInfo.from_dict(json.loads(body.decode("utf-8")))


def fetch_git_tip(url: str, ref: str, timeout: float) -> ChannelInfo:
    """``git ls-remote`` the configured ref — no full clone."""
    # Accept branch, tag, or fully-qualified ref.
    candidates = [ref, f"refs/heads/{ref}", f"refs/tags/{ref}"]
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, *candidates],
            check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git ls-remote failed: {exc}") from exc
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(err or f"git ls-remote exit {result.returncode}")
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0]:
            return ChannelInfo(commit=parts[0].lower(), branch=ref)
    raise RuntimeError(f"no tip for ref {ref!r} on {url}")


def check_for_update(settings: UpdateSettings,
                     fetcher: Callable[[UpdateSettings], ChannelInfo] | None = None
                     ) -> tuple[str, ChannelInfo, ChannelInfo, str]:
    """Compare local install to remote channel.

    Returns ``(status, local, remote, detail)`` where status is
    ``current`` / ``available`` / ``error`` / ``disabled``.
    """
    if not settings.enabled:
        return STATUS_DISABLED, ChannelInfo(), ChannelInfo(), "updates disabled"
    local = read_local_channel(settings)
    try:
        if fetcher is not None:
            remote = fetcher(settings)
        else:
            remote = _default_fetch(settings)
    except Exception as exc:
        log.info("update check failed: %s", exc)
        return STATUS_ERROR, local, ChannelInfo(), str(exc)[:80]
    if not remote.commit and not remote.version:
        return STATUS_ERROR, local, remote, "empty channel"
    if local.commit and remote.commit and commits_match(local.commit,
                                                        remote.commit):
        return STATUS_CURRENT, local, remote, "up to date"
    if local.version and remote.version and local.version == remote.version \
            and not remote.commit:
        return STATUS_CURRENT, local, remote, "up to date"
    if not local.commit and not local.version:
        # Unknown local — treat remote as available so the operator can pin.
        detail = f"update {remote.version or remote.short_commit()}".strip()
        return STATUS_AVAILABLE, local, remote, detail or "update available"
    detail = remote.version or remote.short_commit() or "update"
    if remote.notes:
        detail = f"{detail} — {remote.notes}"[:60]
    return STATUS_AVAILABLE, local, remote, detail


def _default_fetch(settings: UpdateSettings) -> ChannelInfo:
    # Prefer the JSON channel (one small GET, no git needed on the unit).
    if settings.channel_url:
        try:
            return fetch_channel_json(settings.channel_url, settings.timeout_s)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, ValueError) as exc:
            log.info("channel_url failed (%s) — trying git ls-remote", exc)
    if settings.git_url:
        return fetch_git_tip(settings.git_url, settings.git_ref,
                             settings.timeout_s)
    raise RuntimeError("no channel_url or git_url configured")


def start_check(settings: UpdateSettings, state: UpdateState,
                fetcher: Callable[[UpdateSettings], ChannelInfo] | None = None,
                on_done: Callable[[], None] | None = None) -> None:
    """Kick a daemon thread; returns immediately."""
    if not settings.enabled or not settings.check_on_launch:
        state.set(STATUS_DISABLED, detail="updates disabled")
        return

    def worker() -> None:
        state.set(STATUS_CHECKING, detail="checking…")
        status, local, remote, detail = check_for_update(settings, fetcher)
        state.set(status, local=local, remote=remote, detail=detail)
        log.info("update check: %s (%s)", status, detail)
        if status == STATUS_AVAILABLE and settings.auto_apply:
            apply_update(state)
        if on_done is not None:
            on_done()

    threading.Thread(target=worker, name="ranger-update", daemon=True).start()


def apply_update(state: UpdateState,
                 runner: Callable[[], tuple[bool, str]] | None = None
                 ) -> tuple[bool, str]:
    """Run the privileged updater. Returns (ok, message)."""
    state.set(STATUS_APPLYING, detail="installing…")
    run = runner or _default_apply
    try:
        ok, message = run()
    except Exception as exc:
        ok, message = False, f"update failed: {exc}"
    if ok:
        state.set(STATUS_CURRENT, detail=message)
    else:
        state.set(STATUS_ERROR, detail=message)
    return ok, message


def _default_apply() -> tuple[bool, str]:
    script = os.environ.get("RANGER_UPDATE_SCRIPT", UPDATE_SCRIPT)
    argv = ["sudo", "-n", script]
    try:
        result = subprocess.run(argv, check=False, capture_output=True,
                                text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"UPDATE FAILED: {exc}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip().splitlines()
        detail = err[-1] if err else f"exit {result.returncode}"
        return False, f"UPDATE FAILED — {detail}"[:60]
    line = (result.stdout or "").strip().splitlines()
    return True, (line[-1] if line else "UPDATED — RESTARTING")[:60]


def github_raw_channel_url(git_url: str, ref: str) -> str | None:
    """Best-effort raw.githubusercontent.com URL from a github git URL."""
    try:
        parsed = urlparse(git_url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if host not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    return (f"https://raw.githubusercontent.com/{owner}/{repo}/"
            f"{ref}/apps/{CHANNEL_NAME}")
