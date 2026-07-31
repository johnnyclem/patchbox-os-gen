"""Branded Patchbox boot splash for Inky Impression 5.7\"."""

from __future__ import annotations

from PIL import Image, ImageDraw

from . import sysinfo
from .colors import (
    BLACK,
    BLUE,
    GREEN,
    HEIGHT,
    ORANGE,
    RED,
    WHITE,
    WIDTH,
    YELLOW,
)
from .display import blank
from .fonts import font


def render(message: str = "starting audio engine…") -> Image.Image:
    img = blank(BLACK)
    draw = ImageDraw.Draw(img)

    # Colour stripe at top — full 7-colour demo + brand bar
    stripe_h = 14
    colours = [RED, ORANGE, YELLOW, GREEN, BLUE, WHITE, ORANGE]
    seg = WIDTH // len(colours)
    for i, c in enumerate(colours):
        draw.rectangle((i * seg, 0, (i + 1) * seg if i < len(colours) - 1 else WIDTH, stripe_h), fill=c)

    # Large wordmark block
    draw.rectangle((24, 48, WIDTH - 24, 200), outline=ORANGE, width=3)
    draw.rectangle((28, 52, WIDTH - 28, 196), outline=YELLOW, width=1)

    title = font(52, "bold")
    sub = font(22, "regular")
    draw.text((WIDTH // 2, 100), "PATCHBOX", fill=YELLOW, font=title, anchor="mm")
    draw.text((WIDTH // 2, 150), "OS", fill=ORANGE, font=font(36, "bold"), anchor="mm")
    draw.text((WIDTH // 2, 178), "low-latency audio  ·  MIDI  ·  modular", fill=WHITE, font=sub, anchor="mm")

    # Accent chevrons (patch-cable vibe)
    y = 220
    for i, c in enumerate((ORANGE, YELLOW, ORANGE)):
        x0 = 40 + i * 18
        draw.polygon([(x0, y), (x0 + 12, y + 10), (x0, y + 20)], fill=c)
    draw.text((100, y + 2), message, fill=WHITE, font=font(20, "regular"))

    # System facts panel
    panel_top = 268
    draw.rectangle((24, panel_top, WIDTH - 24, HEIGHT - 56), fill=WHITE)
    draw.rectangle((24, panel_top, WIDTH - 24, HEIGHT - 56), outline=BLUE, width=2)

    body = font(18, "regular")
    label = font(16, "bold")
    rows = [
        ("host", sysinfo.hostname()),
        ("ip", sysinfo.primary_ipv4()),
        ("audio", sysinfo.jack_line()),
        ("panel", 'Inky Impression 5.7"  600×448'),
    ]
    yy = panel_top + 16
    for lab, val in rows:
        draw.text((40, yy), lab.upper(), fill=BLUE, font=label)
        draw.text((140, yy), val, fill=BLACK, font=body)
        yy += 28

    # Footer
    draw.rectangle((0, HEIGHT - 44, WIDTH, HEIGHT), fill=GREEN)
    draw.text(
        (24, HEIGHT - 30),
        f"blokas  ·  patchbox  ·  {sysinfo.now_stamp()}",
        fill=WHITE,
        font=font(15, "regular"),
    )
    draw.text((WIDTH - 24, HEIGHT - 30), "A B C D →", fill=WHITE, font=font(15, "bold"), anchor="rm")

    return img
