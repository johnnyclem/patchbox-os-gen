"""Appliance configuration — ``/etc/chordranger/config.toml``.

Deployment state only: panel geometry, writable paths, MIDI backend and port
preference, clock source, RT priority, and the PiSound button map. Nothing
musical lives here; that is ``core.project``.

A missing file yields pure defaults, so ``python main.py`` on a laptop needs
no ``/etc`` and CI needs no fixture. A file that exists but is malformed
raises — a typo in an appliance config should fail loudly at boot rather than
silently run something other than what the operator wrote.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    """The reference panel is the 1280x400 HDMI bar the RK-00pi rig uses; the
    GUI derives its whole layout from these two numbers."""

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

    @property
    def chordsets_dir(self) -> Path:
        return self.data_dir / "chordsets"

    @property
    def styles_dir(self) -> Path:
        return self.data_dir / "styles"


@dataclass(frozen=True, slots=True)
class MidiConfig:
    """``backend`` is "auto" | "mido" | "null".

    ``out_port`` is matched as a case-insensitive substring against the port
    names, so "pisound" finds it whichever ALSA client number it landed on
    this boot. Empty means "take the first preferred port", which on this
    appliance is the DIN socket.
    """

    backend: str = "auto"
    out_port: str = ""
    in_port: str = ""
    clock_out: bool = False
    prefer: tuple[str, ...] = ("pisound", "f_midi", "midi through")


@dataclass(frozen=True, slots=True)
class ClockConfig:
    source: str = "internal"    # "internal" | "midi"
    pll_smooth: float = 0.2
    dropout_ms: float = 1000.0


@dataclass(frozen=True, slots=True)
class EngineConfig:
    rt_priority: int = 0        # SCHED_FIFO priority; 0 = leave scheduling be
    strum_ticks: int = 0
    audition: bool = True


@dataclass(frozen=True, slots=True)
class ButtonConfig:
    """The PiSound button, bridged over a Unix socket the way RK-00pi does it,
    so both apps answer the same ``pisound-btn`` scripts. ``socket`` empty
    derives ``<data_dir>/button.sock``; the appliance points it at
    ``/run/chordranger`` which the unit's RuntimeDirectory= creates."""

    enabled: bool = True
    socket: str = ""
    map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    midi: MidiConfig = field(default_factory=MidiConfig)
    clock: ClockConfig = field(default_factory=ClockConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    button: ButtonConfig = field(default_factory=ButtonConfig)


def load_config(path: Path | None) -> AppConfig:
    if path is None or not Path(path).exists():
        return AppConfig()
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return AppConfig(
        display=_section(DisplayConfig, data.get("display")),
        paths=_paths(data.get("paths")),
        midi=_midi(data.get("midi")),
        clock=_section(ClockConfig, data.get("clock")),
        engine=_section(EngineConfig, data.get("engine")),
        button=_button(data.get("button")))


def _section(cls, raw: dict | None):
    """Unknown keys are dropped rather than raising, so a config written for a
    later firmware still boots this one."""
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


def _button(raw: dict | None) -> ButtonConfig:
    if not raw:
        return ButtonConfig()
    kwargs = {k: v for k, v in raw.items()
              if k in ButtonConfig.__dataclass_fields__ and k != "map"}
    # Gesture ids are upper case by convention, but a config file is written
    # by hand; normalise here so CLICK_1 and click_1 both work.
    kwargs["map"] = {str(k).upper(): str(v)
                     for k, v in (raw.get("map") or {}).items()}
    return ButtonConfig(**kwargs)
