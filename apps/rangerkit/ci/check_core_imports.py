#!/usr/bin/env python3
"""CI guard: an app's engine core must import with no pygame and no audio.

The rule this enforces is the one ``core/__init__.py`` states in every app:
nothing under ``core/`` (or ``data/``, or rangerkit outside ``gui``/
``audio``) may import pygame or open a device at import time. That property
is what makes the engines testable on a headless runner, and it is easy to
lose — one convenience import at module top and CI is the only place that
will ever notice.

Modules are discovered by glob rather than listed, so the check cannot rot
as modules are added.

Usage:  python check_core_imports.py <app_dir> [<app_dir> ...]

For ``apps/rangerkit`` itself, everything except ``gui/`` and
``audio/engine`` is checked. For an app, ``core/`` and ``data/`` are.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

POISONED = ("pygame", "sounddevice", "soundfile")
SKIP_PARTS = ("gui", "tests", "bench", "deploy", "docs", "ci")
SKIP_MODULES = ("rangerkit.audio.engine",)


def modules_under(app_dir: Path) -> list[str]:
    """Dotted names for every core-side module in the tree."""
    if app_dir.name == "rangerkit":
        roots = [app_dir]
        package_parent = app_dir.parent
    else:
        roots = [d for d in (app_dir / "core", app_dir / "data") if d.is_dir()]
        package_parent = app_dir
    names = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(package_parent)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            name = ".".join(parts)
            if name and name not in SKIP_MODULES:
                names.append(name)
    return names


def check(app_dir: Path) -> list[str]:
    app_dir = app_dir.resolve()
    # The app root first (so ``core`` resolves), then apps/ (so ``rangerkit``
    # resolves) — the same order main.py and conftest.py establish.
    for entry in (str(app_dir), str(app_dir.parent)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    for name in POISONED:
        sys.modules[name] = None            # import raises ImportError
    failures = []
    for name in modules_under(app_dir):
        try:
            importlib.import_module(name)
        except Exception as exc:            # noqa: BLE001 - report, not raise
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok {name}")
    return failures


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    failed = []
    for arg in argv:
        failed += check(Path(arg))
    if failed:
        print("\nCORE IMPORT FAILURES (pygame/audio poisoned):",
              file=sys.stderr)
        for line in failed:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
