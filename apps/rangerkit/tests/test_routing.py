"""The routing matrix: pure-value behavior, config round-trips, autobind."""
from __future__ import annotations

from rangerkit.midi_io import NullMidiIO
from rangerkit.routing import (ALL_CHANNELS, DIN_IN, DIN_OUT, INTERNAL,
                               Route, RoutingMatrix, TRS_A_IN, TRS_A_OUT,
                               USB_IN, USB_OUT, autobind)


def test_matrix_is_a_value():
    empty = RoutingMatrix()
    route = Route(src=DIN_IN, dst=USB_OUT)
    one = empty.with_route(route)
    assert not empty.routes and route in one.routes
    assert one.without_route(route) == empty
    assert one.toggled(route) == empty
    assert empty.toggled(route) == one


def test_targets_channel_filter_and_rewrite():
    matrix = (RoutingMatrix()
              .with_route(Route(src=DIN_IN, dst=USB_OUT))
              .with_route(Route(src=DIN_IN, dst=TRS_A_OUT, channel=9))
              .with_route(Route(src=USB_IN, dst=DIN_OUT, to_channel=4)))
    assert matrix.targets(DIN_IN, 0) == ((USB_OUT, 0),)
    assert matrix.targets(DIN_IN, 9) == ((TRS_A_OUT, 9), (USB_OUT, 9))
    assert matrix.targets(USB_IN, 2) == ((DIN_OUT, 4),)
    assert matrix.targets(TRS_A_IN, 0) == ()


def test_config_round_trip():
    matrix = (RoutingMatrix()
              .with_route(Route(src=DIN_IN, dst=INTERNAL, channel=3,
                                to_channel=5))
              .with_route(Route(src=USB_IN, dst=DIN_OUT)))
    again = RoutingMatrix.from_config(matrix.to_config())
    assert again == matrix


def test_from_config_drops_unknown_endpoints():
    matrix = RoutingMatrix.from_config([
        {"src": "din_in", "dst": "usb_out"},
        {"src": "warp_core", "dst": "usb_out"},
        {"src": "din_in", "dst": "holodeck"},
    ])
    assert matrix.routes == frozenset({Route(src=DIN_IN, dst=USB_OUT)})


def test_default_route_is_omni():
    route = Route(src=DIN_IN, dst=USB_OUT)
    assert route.channel == ALL_CHANNELS
    assert route.matches(DIN_IN, 0) and route.matches(DIN_IN, 15)
    assert route.rewrite(7) == 7


def test_autobind_survives_a_portless_backend():
    """A rig with no matching ports still boots; nothing raises, nothing
    binds, and INTERNAL is never offered to the backend."""
    matrix = (RoutingMatrix()
              .with_route(Route(src=DIN_IN, dst=INTERNAL))
              .with_route(Route(src=USB_IN, dst=USB_OUT)))
    autobind(NullMidiIO(), matrix)
