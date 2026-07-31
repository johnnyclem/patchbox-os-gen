"""Inky Impression 7-colour ACeP palette (UC8159).

Indices must match inky.inky_uc8159 so palette-mode images transfer 1:1.
"""

BLACK = 0
WHITE = 1
GREEN = 2
BLUE = 3
RED = 4
YELLOW = 5
ORANGE = 6
CLEAN = 7

# RGB triples for PIL putpalette / simulation export
RGB = {
    BLACK: (0, 0, 0),
    WHITE: (255, 255, 255),
    GREEN: (0, 255, 0),
    BLUE: (0, 0, 255),
    RED: (255, 0, 0),
    YELLOW: (255, 255, 0),
    ORANGE: (255, 140, 0),
}

WIDTH = 600
HEIGHT = 448


def pil_palette() -> list[int]:
    """Flat 768-entry palette for Image mode 'P'."""
    flat: list[int] = []
    for i in range(8):
        r, g, b = RGB.get(i, (255, 255, 255))
        flat.extend((r, g, b))
    flat.extend([0] * (768 - len(flat)))
    return flat
