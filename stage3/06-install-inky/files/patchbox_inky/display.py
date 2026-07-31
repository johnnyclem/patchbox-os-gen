"""Open the Inky panel (or simulate to PNG)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from .colors import HEIGHT, WIDTH, pil_palette


def blank(fill: int = 1) -> Image.Image:
    """New palette-mode canvas sized for the 5.7\" panel."""
    img = Image.new("P", (WIDTH, HEIGHT), fill)
    img.putpalette(pil_palette())
    return img


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "P":
        img = img.copy()
        img.putpalette(pil_palette())
    return img.convert("RGB")


def open_display(
    force_type: str | None = "5.7",
    simulate: bool = False,
    verbose: bool = True,
) -> Any:
    """Return an Inky-like object with width/height/set_image/show.

    Default force_type is the 5.7\" UC8159 (600×448). EEPROM auto-detect is
    opt-in via force_type=None or \"auto\" — mis-detect was a likely cause of
    half-screen paints on some stacks.
    """
    if simulate:
        if verbose:
            print(f"[inky] simulate mode {WIDTH}x{HEIGHT}", file=sys.stderr)
        return _SimDisplay()

    from inky.inky_uc8159 import Inky as InkyUC8159

    # Normalize aliases
    if force_type in ("auto",):
        force_type = None
    if force_type in ("impressions", "7colour", "uc8159", "5.7", "5.7in"):
        disp = InkyUC8159(resolution=(WIDTH, HEIGHT))
        if verbose:
            print(
                f"[inky] forced UC8159 {disp.width}x{disp.height} "
                f"(resolution={getattr(disp, 'resolution', None)})",
                file=sys.stderr,
            )
        _warn_if_not_full_frame(disp)
        return disp

    # Explicit auto / unknown: try EEPROM then fall back to 5.7"
    try:
        from inky.auto import auto

        disp = auto(ask_user=False, verbose=verbose)
        if verbose:
            print(
                f"[inky] auto-detected {type(disp).__name__} "
                f"{getattr(disp, 'width', '?')}x{getattr(disp, 'height', '?')}",
                file=sys.stderr,
            )
        # If auto returned a non-5.7 size, prefer forced 5.7 for this product image
        w, h = getattr(disp, "width", 0), getattr(disp, "height", 0)
        if (w, h) != (WIDTH, HEIGHT):
            print(
                f"[inky] WARNING: auto size {w}x{h} != {WIDTH}x{HEIGHT}; "
                f"forcing UC8159 5.7\" (half-screen often means wrong geometry)",
                file=sys.stderr,
            )
            disp = InkyUC8159(resolution=(WIDTH, HEIGHT))
        _warn_if_not_full_frame(disp)
        return disp
    except Exception as exc:  # noqa: BLE001
        print(f"[inky] auto failed ({exc}); forcing UC8159 {WIDTH}x{HEIGHT}", file=sys.stderr)
        disp = InkyUC8159(resolution=(WIDTH, HEIGHT))
        _warn_if_not_full_frame(disp)
        return disp


def _warn_if_not_full_frame(disp: Any) -> None:
    w, h = getattr(disp, "width", None), getattr(disp, "height", None)
    if (w, h) != (WIDTH, HEIGHT):
        print(
            f"[inky] WARNING: driver reports {w}x{h}, expected {WIDTH}x{HEIGHT}",
            file=sys.stderr,
        )


def push(display: Any, img: Image.Image, label: str = "") -> None:
    """Resize if needed and send a full refresh (~30s on 7-colour panels)."""
    w = getattr(display, "width", WIDTH)
    h = getattr(display, "height", HEIGHT)
    if img.size != (w, h):
        print(
            f"[inky] resizing canvas {img.size} → {(w, h)}",
            file=sys.stderr,
        )
        img = img.resize((w, h), Image.Resampling.NEAREST)
    # Ensure palette mode for UC8159 path (indices must match library colours).
    if img.mode != "P":
        img = img.convert("P")
    display.set_image(img)
    if label:
        print(f"[inky] full refresh: {label} ({w}x{h}) — may take ~30s…", file=sys.stderr)
    display.show()
    if label:
        print(f"[inky] done: {label}", file=sys.stderr)


class _SimDisplay:
    width = WIDTH
    height = HEIGHT
    BLACK = 0
    WHITE = 1
    GREEN = 2
    BLUE = 3
    RED = 4
    YELLOW = 5
    ORANGE = 6

    def __init__(self) -> None:
        self._img: Image.Image | None = None
        self.out_dir = Path(os.environ.get("PATCHBOX_INKY_SIM_DIR", "/tmp"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:  # noqa: ARG002
        self._img = image

    def show(self, busy_wait: bool = True) -> None:  # noqa: ARG002
        if self._img is None:
            return
        self.counter += 1
        path = self.out_dir / f"patchbox-inky-{self.counter:02d}.png"
        latest = self.out_dir / "patchbox-inky-last.png"
        rgb = to_rgb(self._img)
        rgb.save(path)
        rgb.save(latest)
        print(f"[simulate] wrote {path}")
