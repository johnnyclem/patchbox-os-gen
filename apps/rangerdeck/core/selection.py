"""Which Ranger tiles the launcher shows.

Bake-time defaults live in ``/etc/rangerdeck/config.toml`` ``[deck] apps``.
On the unit, the user (or ``patchbox-setup rangers …``) can override that
list without rewriting the package config:

    /var/lib/rangerdeck/enabled-apps.txt     one app name per line
    # or a single comma-separated line

The deck reads the override when present; otherwise it uses the config
order. Writing always updates the override file (and, when root-owned
config is writable, the config.toml ``apps`` list too).
"""
from __future__ import annotations

from pathlib import Path

from core.registry import KNOWN_APPS

__all__ = [
    "DEFAULT_ENABLED_PATH",
    "KNOWN_NAMES",
    "load_enabled",
    "save_enabled",
    "resolve_order",
]

DEFAULT_ENABLED_PATH = Path("/var/lib/rangerdeck/enabled-apps.txt")
KNOWN_NAMES: tuple[str, ...] = tuple(name for name, _, _ in KNOWN_APPS)


def load_enabled(path: Path | None = None) -> tuple[str, ...] | None:
    """Return the override list, or ``None`` when no override file exists."""
    path = path or DEFAULT_ENABLED_PATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    names: list[str] = []
    seen: set[str] = set()
    for raw in text.replace(",", "\n").splitlines():
        name = raw.strip().lower()
        if not name or name.startswith("#"):
            continue
        if name not in KNOWN_NAMES or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def resolve_order(config_apps: tuple[str, ...] = (),
                  path: Path | None = None) -> tuple[str, ...]:
    """Effective tile order: override file wins, else config, else suite."""
    override = load_enabled(path)
    if override is not None:
        return override
    if config_apps:
        return tuple(n for n in config_apps if n in KNOWN_NAMES)
    return KNOWN_NAMES


def save_enabled(names: tuple[str, ...] | list[str],
                 path: Path | None = None,
                 config_toml: Path | None = None) -> tuple[str, ...]:
    """Persist the tile list. Returns the cleaned name tuple."""
    path = path or DEFAULT_ENABLED_PATH
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw).strip().lower()
        if name not in KNOWN_NAMES or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# RangerDeck tile list — one app per line (patchbox-setup / SETTINGS)\n"
        + "\n".join(cleaned) + ("\n" if cleaned else ""),
        encoding="utf-8",
    )
    if config_toml is not None and config_toml.is_file():
        _rewrite_config_apps(config_toml, cleaned)
    return tuple(cleaned)


def _rewrite_config_apps(config_toml: Path, names: list[str]) -> None:
    """Best-effort update of ``apps = […]`` in config.toml."""
    import re

    text = config_toml.read_text(encoding="utf-8")
    if len(names) <= 3:
        body = ", ".join(f'"{n}"' for n in names)
        replacement = f"apps = [{body}]"
    else:
        inner = ",\n        ".join(f'"{n}"' for n in names)
        replacement = f"apps = [\n        {inner}\n       ]"
    new, n = re.subn(
        r"(?m)^\s*apps\s*=\s*\[.*?\]",
        replacement,
        text,
        count=1,
        flags=re.S,
    )
    if n:
        try:
            config_toml.write_text(new, encoding="utf-8")
        except OSError:
            pass  # /etc may be root-owned; override file is enough
