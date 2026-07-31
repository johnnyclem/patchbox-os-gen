"""System status screen (non-interactive snapshot)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from . import jackutil, sysinfo
from .colors import BLACK, BLUE, GREEN, HEIGHT, ORANGE, WHITE, WIDTH, YELLOW
from .display import blank
from .fonts import font


def render(title: str = "Patchbox OS") -> Image.Image:
    img = blank(WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 64), fill=BLACK)
    draw.text((24, 32), title, fill=YELLOW, font=font(32, "bold"), anchor="lm")
    draw.rectangle((0, 64, WIDTH, 72), fill=ORANGE)

    label_f = font(18, "bold")
    body_f = font(20, "regular")
    graph = jackutil.fetch_graph()
    conn_n = len(graph.connections) if graph.error is None else 0
    port_n = len(graph.ports) if graph.error is None else 0

    rows = [
        ("Host", sysinfo.hostname()),
        ("IP", sysinfo.primary_ipv4()),
        ("Audio", sysinfo.jack_line()),
        ("Graph", f"{port_n} ports  ·  {conn_n} links" if graph.error is None else graph.error),
        ("Load", sysinfo.load_avg()),
        ("Memory", sysinfo.mem_human()),
        ("Uptime", sysinfo.uptime_human()),
    ]
    y = 96
    for lab, val in rows:
        draw.text((28, y), lab, fill=BLUE, font=label_f)
        draw.text((160, y), val, fill=BLACK, font=body_f)
        y += 38

    draw.rectangle((0, HEIGHT - 48, WIDTH, HEIGHT), fill=GREEN)
    draw.text(
        (24, HEIGHT - 24),
        f"status  ·  {sysinfo.now_stamp()}  ·  600×448",
        fill=WHITE,
        font=font(15, "regular"),
        anchor="lm",
    )
    return img
