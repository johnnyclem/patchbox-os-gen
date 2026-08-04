"""A patch is a value — every number one voice needs to make its sound.

Immutable and JSON-able, like all material in the family: presets store
exactly this, morphing interpolates exactly this, and the panel edits it
by replacement. Time values are seconds, levels are 0..1, tuning is cents.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from core.dsp.filters import MODES
from core.dsp.oscillators import ENGINES
from core.dsp.tables import SHAPES

LFO_SHAPES = ("sine", "triangle", "square", "sh")
LFO_DESTS = ("none", "pitch", "cutoff", "wt_position", "pd_warp",
             "fm_index")


@dataclass(frozen=True, slots=True)
class Patch:
    name: str = "INIT"
    engine: str = "va"
    shape: str = "saw"           # va
    detune_cents: float = 4.0    # second osc spread (va/wavetable)
    fm_ratio: float = 2.0        # fm
    fm_index: float = 0.8
    wt_position: float = 0.0     # wavetable scan
    pd_warp: float = 0.4         # phase distortion
    cutoff: float = 0.8          # 0..1 log 40 Hz..16 kHz
    resonance: float = 0.15
    filter_mode: str = "lp"
    filter_env: float = 0.3      # cutoff modulation depth from env 2
    amp_env: tuple = (0.005, 0.15, 0.75, 0.25)      # ADSR seconds/level
    mod_env: tuple = (0.01, 0.3, 0.0, 0.3)
    lfo_rate: float = 1.2        # Hz
    lfo_depth: float = 0.0
    lfo_dest: str = "none"
    lfo_shape: str = "sine"
    drive: float = 0.0
    chorus: float = 0.0
    delay_send: float = 0.0

    def normalised(self) -> "Patch":
        def clip(v, lo, hi):
            return max(lo, min(hi, float(v)))

        def adsr(t):
            t = tuple(float(v) for v in t)[:4] + (0.0,) * (4 - len(t))
            return (clip(t[0], 0.001, 8.0), clip(t[1], 0.001, 8.0),
                    clip(t[2], 0.0, 1.0), clip(t[3], 0.005, 12.0))

        return replace(
            self, name=str(self.name)[:12] or "INIT",
            engine=self.engine if self.engine in ENGINES else "va",
            shape=self.shape if self.shape in SHAPES else "saw",
            detune_cents=clip(self.detune_cents, 0.0, 50.0),
            fm_ratio=clip(self.fm_ratio, 0.25, 16.0),
            fm_index=clip(self.fm_index, 0.0, 4.0),
            wt_position=clip(self.wt_position, 0.0, 1.0),
            pd_warp=clip(self.pd_warp, 0.0, 1.0),
            cutoff=clip(self.cutoff, 0.0, 1.0),
            resonance=clip(self.resonance, 0.0, 1.0),
            filter_mode=self.filter_mode if self.filter_mode in MODES
            else "lp",
            filter_env=clip(self.filter_env, -1.0, 1.0),
            amp_env=adsr(self.amp_env), mod_env=adsr(self.mod_env),
            lfo_rate=clip(self.lfo_rate, 0.02, 30.0),
            lfo_depth=clip(self.lfo_depth, 0.0, 1.0),
            lfo_dest=self.lfo_dest if self.lfo_dest in LFO_DESTS
            else "none",
            lfo_shape=self.lfo_shape if self.lfo_shape in LFO_SHAPES
            else "sine",
            drive=clip(self.drive, 0.0, 1.0),
            chorus=clip(self.chorus, 0.0, 1.0),
            delay_send=clip(self.delay_send, 0.0, 1.0))

    def to_config(self) -> dict:
        return {"name": self.name, "engine": self.engine,
                "shape": self.shape, "detune_cents": self.detune_cents,
                "fm_ratio": self.fm_ratio, "fm_index": self.fm_index,
                "wt_position": self.wt_position, "pd_warp": self.pd_warp,
                "cutoff": self.cutoff, "resonance": self.resonance,
                "filter_mode": self.filter_mode,
                "filter_env": self.filter_env,
                "amp_env": list(self.amp_env),
                "mod_env": list(self.mod_env),
                "lfo_rate": self.lfo_rate, "lfo_depth": self.lfo_depth,
                "lfo_dest": self.lfo_dest, "lfo_shape": self.lfo_shape,
                "drive": self.drive, "chorus": self.chorus,
                "delay_send": self.delay_send}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Patch":
        raw = dict(raw or {})
        for key in ("amp_env", "mod_env"):
            if key in raw:
                raw[key] = tuple(raw[key])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items()
                      if k in known}).normalised()


#: The numeric fields morphing interpolates; everything else snaps.
NUMERIC_FIELDS = ("detune_cents", "fm_ratio", "fm_index", "wt_position",
                  "pd_warp", "cutoff", "resonance", "filter_env",
                  "lfo_rate", "lfo_depth", "drive", "chorus",
                  "delay_send")
