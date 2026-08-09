"""The shared appliance config — ``/etc/<app>/config.toml``.

Deployment state only: panel geometry, writable paths, MIDI backend and port
preference, routing, clock source, RT priority, the button map, the pots
source, and (for the audio apps) the audio backend. Nothing musical lives
here; that is each app's project file.

Loader rules, identical across the family:

* a missing file yields pure defaults, so ``python main.py`` on a laptop
  needs no ``/etc`` and CI needs no fixture;
* a file that exists but is malformed raises — a typo in an appliance config
  should fail loudly at boot rather than silently run something other than
  what the operator wrote;
* unknown keys inside a known table are dropped, so a config written for a
  later firmware still boots this one.

Apps with sections of their own read them from ``RangerConfig.extra`` (every
table this loader did not recognise, verbatim) rather than subclassing the
loader.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    """The reference panel is the 1280x400 HDMI bar; the GUI derives its
    whole layout from these two numbers."""

    width: int = 1280
    height: int = 400
    fullscreen: bool = False
    theme: str = "industrial"
    fps: int = 60


@dataclass(frozen=True, slots=True)
class PathsConfig:
    data_dir: Path = Path("data")
    presets_dir: Path = Path("data/presets")

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


@dataclass(frozen=True, slots=True)
class MidiConfig:
    """``backend`` is "auto" | "alsa" | "mido" | "null".

    ``auto`` (default) tries native ALSA seq first, then mido/rtmidi.
    Both talk to the same ALSA sequencer on the Pi — "mido" is the library
    name, not a separate bus. Pin ``alsa`` for appliance parity with RK-00pi.

    ``out_port`` is matched as a case-insensitive substring against the port
    names, so "pisound" / "pimidi" finds the HAT whichever client number it
    landed on this boot. Empty means "take the first preferred port".
    """

    backend: str = "auto"
    out_port: str = ""
    in_port: str = ""
    clock_out: bool = False
    prefer: tuple[str, ...] = (
        "pimidi0:a", "pimidi0", "pimidi", "pisound", "f_midi", "usb",
        "midi through",
    )


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """``routes`` is a list of ``{src, dst, channel, to_channel}`` tables —
    the shape ``rangerkit.routing.RoutingMatrix.from_config`` reads."""

    routes: tuple = ()


@dataclass(frozen=True, slots=True)
class ClockConfig:
    source: str = "internal"    # "internal" | "midi"
    pll_smooth: float = 0.2
    dropout_ms: float = 1000.0


@dataclass(frozen=True, slots=True)
class EngineConfig:
    rt_priority: int = 0        # SCHED_FIFO priority; 0 = leave scheduling be


@dataclass(frozen=True, slots=True)
class ButtonConfig:
    """The PiSound button, bridged over a Unix socket. ``socket`` empty
    derives ``<data_dir>/button.sock``; the appliance points it at
    ``/run/<app>`` which the unit's RuntimeDirectory= creates."""

    enabled: bool = True
    socket: str = ""
    map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PotsConfig:
    """See ``rangerkit.pots``. ``channel`` -1 means omni."""

    source: str = "midi_cc"     # "midi_cc" | "socket" | "none"
    socket: str = ""
    cc_a: int = 20
    cc_b: int = 21
    channel: int = -1
    map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AudioConfig:
    """Only the audio apps read this. The internal render rate is 48 kHz by
    design — the DAC path may run higher, the synthesis does not."""

    backend: str = "auto"       # "auto" | "jack" | "alsa" | "null"
    device: str = ""
    sample_rate: int = 48000
    block_frames: int = 256


@dataclass(frozen=True, slots=True)
class RangerConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    midi: MidiConfig = field(default_factory=MidiConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    clock: ClockConfig = field(default_factory=ClockConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    button: ButtonConfig = field(default_factory=ButtonConfig)
    pots: PotsConfig = field(default_factory=PotsConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    extra: dict = field(default_factory=dict)


_KNOWN = ("display", "paths", "midi", "routing", "clock", "engine", "button",
          "pots", "audio")


def load_config(path: Path | None) -> RangerConfig:
    if path is None or not Path(path).exists():
        return RangerConfig()
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return RangerConfig(
        display=section(DisplayConfig, data.get("display")),
        paths=_paths(data.get("paths")),
        midi=_midi(data.get("midi")),
        routing=_routing(data.get("routing")),
        clock=section(ClockConfig, data.get("clock")),
        engine=section(EngineConfig, data.get("engine")),
        button=_mapped(ButtonConfig, data.get("button")),
        pots=_mapped(PotsConfig, data.get("pots")),
        audio=section(AudioConfig, data.get("audio")),
        extra={k: v for k, v in data.items() if k not in _KNOWN})


def section(cls, raw: dict | None):
    """Build a section dataclass, dropping unknown keys. Public because app
    config modules use it for their own tables out of ``extra``."""
    if not raw:
        return cls()
    fields = cls.__dataclass_fields__
    return cls(**{k: v for k, v in raw.items() if k in fields})


def _paths(raw: dict | None) -> PathsConfig:
    if not raw:
        return PathsConfig()
    data_dir = Path(raw.get("data_dir", "data"))
    presets = Path(raw["presets_dir"]) if "presets_dir" in raw \
        else data_dir / "presets"
    return PathsConfig(data_dir=data_dir, presets_dir=presets)


def _midi(raw: dict | None) -> MidiConfig:
    if not raw:
        return MidiConfig()
    kwargs = {k: v for k, v in raw.items()
              if k in MidiConfig.__dataclass_fields__ and k != "prefer"}
    if "prefer" in raw:
        kwargs["prefer"] = tuple(str(v) for v in raw["prefer"])
    return MidiConfig(**kwargs)


def _routing(raw: dict | None) -> RoutingConfig:
    if not raw:
        return RoutingConfig()
    routes = raw.get("routes")
    return RoutingConfig(routes=tuple(routes) if routes else ())


def _mapped(cls, raw: dict | None):
    """Sections with a ``map`` sub-table (button, pots). Gesture/pot ids are
    upper case by convention, but a config file is written by hand; normalise
    here so CLICK_1 and click_1 both work."""
    if not raw:
        return cls()
    kwargs = {k: v for k, v in raw.items()
              if k in cls.__dataclass_fields__ and k != "map"}
    kwargs["map"] = {str(k).upper(): str(v)
                     for k, v in (raw.get("map") or {}).items()}
    return cls(**kwargs)
