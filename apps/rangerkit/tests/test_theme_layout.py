"""Panel geometry at the three shipped sizes — the resolver every app uses."""
from __future__ import annotations

import pytest

from rangerkit.testkit import GEOMETRIES

theme = pytest.importorskip("rangerkit.gui.theme",
                            reason="pygame not installed")


@pytest.mark.parametrize("size", GEOMETRIES)
def test_layout_covers_the_panel_without_overlap(size):
    layout = theme.Layout.for_size(size, tab_count=5)
    width, height = size
    assert (layout.width, layout.height) == size
    assert not layout.content.colliderect(layout.transport)
    for tab in layout.tabs:
        assert not tab.colliderect(layout.content)
    assert layout.content.width > 0 and layout.content.height > 0


def test_wide_bar_uses_side_rails():
    layout = theme.Layout.for_size((1280, 400), tab_count=5)
    assert layout.wide
    assert layout.transport.width == theme.RAIL_W
    assert layout.tabs[0].x == 1280 - theme.TAB_RAIL_W
    # Tabs slice the full height with no dead strip at the bottom.
    assert layout.tabs[-1].bottom == 400


@pytest.mark.parametrize("size", [(800, 480), (480, 800)])
def test_stacked_layouts_band_top_and_tab_bottom(size):
    layout = theme.Layout.for_size(size, tab_count=5)
    assert not layout.wide
    assert layout.transport.height == theme.TRANSPORT_H
    assert all(tab.bottom == size[1] for tab in layout.tabs)
    assert layout.tabs[-1].right == size[0]


@pytest.mark.parametrize("size", GEOMETRIES)
def test_tabs_meet_touch_minimum(size):
    layout = theme.Layout.for_size(size, tab_count=5)
    for tab in layout.tabs:
        assert min(tab.width, tab.height) >= theme.TOUCH_MIN


def test_colorways_apply_and_report():
    for name in ("industrial", "mono", "dusk"):
        assert theme.apply(name) == name
    theme.apply("industrial")
