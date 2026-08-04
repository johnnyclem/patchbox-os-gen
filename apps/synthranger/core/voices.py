"""Voices and the Synth — the instrument behind the ``internal`` endpoint.

Speaks the same protocol the suite's sampler and SimpleSynth do —
``note_on / note_off / all_off / control / render / hanging_voices`` — so
the shared ``SynthMidiBridge`` drives it unchanged and the engine's
release book releases synth voices exactly as it releases external gear.

The internal contract (see docs/ARCHITECTURE.md): channel = part index;
CC 1 is the mod wheel, CC 74 a cutoff offset, CC 16/17 the XY pad — all
per part; channel 15 CC 7 is the master level. Patches themselves never
travel as MIDI: the App swaps the immutable parts tuple when the
snapshot's ``parts_rev`` moves.

A voice reads its part's *effective* patch (morph applied) fresh every
block, so edits and morphs land on sounding notes. Control-rate facts
(filter cutoff, LFO, mod matrix) are per-block; audio-rate facts (phase,
envelopes) are per-sample and vectorized. Nothing in here loops over
samples in Python.
"""
from __future__ import annotations

import random

import numpy as np

from rangerkit.audio import BLOCK_FRAMES, SAMPLE_RATE

from core.dsp import oscillators
from core.dsp.effects import Delay
from core.dsp.filters import VoiceFilter
from core.envelope import Envelope
from core.fxchain import PartFx
from core.lfo import Lfo
from core.modmatrix import resolve
from core.parts import PARTS, default_parts

MASTER_CHANNEL = 15
CC_MOD_WHEEL, CC_CUTOFF, CC_XY_X, CC_XY_Y, CC_LEVEL = 1, 74, 16, 17, 7
_TIMBRE_FIELD = {"va": "detune_cents", "fm": "fm_index",
                 "wavetable": "wt_position", "pd": "pd_warp"}
_TIMBRE_SCALE = {"va": 30.0, "fm": 2.0, "wavetable": 1.0, "pd": 1.0}


def note_freq(note: int, cents: float = 0.0) -> float:
    return 440.0 * 2.0 ** ((note - 69 + cents / 100.0) / 12.0)


class _Voice:
    __slots__ = ("part_index", "note", "velocity", "phase", "phase2",
                 "amp_env", "mod_env", "filter", "released", "seq")

    def __init__(self, part_index: int, note: int, velocity: int,
                 sample_rate: int, seq: int) -> None:
        self.part_index = part_index
        self.note = note
        self.velocity = velocity
        self.phase = 0.0
        self.phase2 = 0.0
        self.amp_env = Envelope(sample_rate)
        self.mod_env = Envelope(sample_rate)
        self.amp_env.gate_on()
        self.mod_env.gate_on()
        self.filter = VoiceFilter(sample_rate)
        self.released = False
        self.seq = seq

    def dead(self) -> bool:
        return self.amp_env.idle()

    def render(self, frames: int, patch, offsets: dict,
               sample_rate: int) -> np.ndarray:
        pitch = offsets.get("pitch", 0.0) * 12.0
        freq = note_freq(self.note) * 2.0 ** (pitch / 12.0)
        timbre = offsets.get("timbre", 0.0)
        if timbre:
            from dataclasses import replace
            field = _TIMBRE_FIELD.get(patch.engine, "wt_position")
            value = getattr(patch, field) \
                + timbre * _TIMBRE_SCALE.get(patch.engine, 1.0)
            patch = replace(patch, **{field: value}).normalised()
        step = freq / sample_rate
        ramp = np.arange(1, frames + 1, dtype=np.float64)
        phases = self.phase + step * ramp
        wave = oscillators.render(patch.engine, phases, freq, patch)
        self.phase = float(phases[-1] % 1.0)
        if patch.engine in ("va", "wavetable") and patch.detune_cents:
            freq2 = note_freq(self.note, patch.detune_cents) \
                * 2.0 ** (pitch / 12.0)
            phases2 = self.phase2 + (freq2 / sample_rate) * ramp
            wave = 0.5 * (wave + oscillators.render(
                patch.engine, phases2, freq2, patch))
            self.phase2 = float(phases2[-1] % 1.0)
        mod = self.mod_env.render(frames, patch.mod_env)
        cutoff = patch.cutoff + offsets.get("cutoff", 0.0) \
            + patch.filter_env * float(mod[-1])
        res = patch.resonance + offsets.get("resonance", 0.0)
        wave = self.filter.process(wave.astype(np.float32),
                                   min(1.0, max(0.0, cutoff)),
                                   res, patch.filter_mode)
        amp = self.amp_env.render(frames, patch.amp_env) \
            * (self.velocity / 127.0)
        return (wave * amp).astype(np.float32)


class Synth:
    """8 voices × 4 parts at 48 kHz — the documented floor."""

    def __init__(self, parts=None, sample_rate: int = SAMPLE_RATE,
                 seed: int = 0x517) -> None:
        self.sample_rate = sample_rate
        self.parts = tuple(parts) if parts else default_parts()
        self.rng = random.Random(seed)
        self._keyed: dict[tuple[int, int], _Voice] = {}
        self._released: list[_Voice] = []
        self._lfos = [Lfo() for _ in range(PARTS)]
        self._fx = [PartFx(sample_rate) for _ in range(PARTS)]
        self._controls = [{"mod_wheel": 0.0, "xy_x": 0.5, "xy_y": 0.5,
                           "cutoff_offset": 0.0} for _ in range(PARTS)]
        self._delay = Delay(sample_rate)
        self._delay_s = 0.375
        self.level = 1.0
        self._seq = 0

    # --- the synth protocol ----------------------------------------------------
    def note_on(self, channel: int, note: int, velocity: int) -> None:
        if not 0 <= channel < PARTS:
            return
        part = self.parts[channel]
        key = (channel, note)
        held = self._keyed.pop(key, None)
        if held is not None:
            held.released = True
            held.amp_env.gate_off()
            held.mod_env.gate_off()
            self._released.append(held)
        mine = [v for v in self._all() if v.part_index == channel]
        while len(mine) >= part.poly:
            victim = min(mine, key=lambda v: v.seq)
            self._drop(victim)
            mine.remove(victim)
        self._seq += 1
        self._keyed[key] = _Voice(channel, note, velocity,
                                  self.sample_rate, self._seq)

    def note_off(self, channel: int, note: int) -> None:
        voice = self._keyed.pop((channel, note), None)
        if voice is not None:
            voice.released = True
            voice.amp_env.gate_off()
            voice.mod_env.gate_off()
            self._released.append(voice)

    def all_off(self, channel: int | None = None) -> None:
        for key in [k for k in self._keyed
                    if channel is None or k[0] == channel]:
            self.note_off(*key)

    def control(self, channel: int, number: int, value: int) -> None:
        if channel == MASTER_CHANNEL:
            if number == CC_LEVEL:
                self.level = min(1.27, value / 100.0)
            return
        if not 0 <= channel < PARTS:
            return
        state = self._controls[channel]
        if number == CC_MOD_WHEEL:
            state["mod_wheel"] = value / 127.0
        elif number == CC_CUTOFF:
            state["cutoff_offset"] = (value - 64) / 127.0
        elif number == CC_XY_X:
            state["xy_x"] = value / 127.0
        elif number == CC_XY_Y:
            state["xy_y"] = value / 127.0

    def set_parts(self, parts) -> None:
        self.parts = tuple(part.normalised() for part in parts)

    def set_tempo(self, bpm: float) -> None:
        # A dotted-eighth echo: 0.75 beats at the current tempo.
        self._delay_s = 0.75 * 60.0 / max(20.0, min(300.0, float(bpm)))

    # --- ledgers ---------------------------------------------------------------
    def hanging_voices(self) -> set[tuple[int, int]]:
        return set(self._keyed)

    def sounding(self) -> int:
        return sum(1 for v in self._all() if not v.dead())

    def _all(self):
        yield from self._keyed.values()
        yield from self._released

    def _drop(self, voice: _Voice) -> None:
        self._keyed.pop((voice.part_index, voice.note), None)
        if voice in self._released:
            self._released.remove(voice)

    # --- rendering -------------------------------------------------------------
    def render(self, frames: int = BLOCK_FRAMES) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        send = np.zeros(frames, dtype=np.float32)
        by_part: dict[int, list] = {}
        for voice in list(self._all()):
            if voice.dead():
                if voice in self._released:
                    self._released.remove(voice)
                continue
            by_part.setdefault(voice.part_index, []).append(voice)
        for index, voices in by_part.items():
            part = self.parts[index]
            if part.muted:
                continue
            patch = part.effective()
            controls = self._controls[index]
            lfo = self._lfos[index].step(patch.lfo_rate, patch.lfo_shape,
                                         frames, self.sample_rate,
                                         self.rng) * patch.lfo_depth
            mono = np.zeros(frames, dtype=np.float32)
            for voice in voices:
                sources = {"xy_x": controls["xy_x"],
                           "xy_y": controls["xy_y"],
                           "mod_wheel": controls["mod_wheel"],
                           "velocity": voice.velocity / 127.0,
                           "lfo": lfo}
                offsets = resolve(part.mods, sources)
                offsets["cutoff"] = offsets.get("cutoff", 0.0) \
                    + controls["cutoff_offset"]
                if patch.lfo_dest == "pitch":
                    offsets["pitch"] = offsets.get("pitch", 0.0) \
                        + lfo * 0.08
                elif patch.lfo_dest == "cutoff":
                    offsets["cutoff"] += lfo * 0.5
                elif patch.lfo_dest in ("wt_position", "pd_warp",
                                        "fm_index"):
                    offsets["timbre"] = offsets.get("timbre", 0.0) + lfo
                mono += voice.render(frames, patch, offsets,
                                     self.sample_rate)
            mono = self._fx[index].process(mono, patch)
            if patch.delay_send > 0.0:
                send += mono * patch.delay_send
            angle = (part.pan + 1.0) * (np.pi / 4)
            gain = part.level * 0.5          # headroom across four parts
            out[:, 0] += mono * gain * float(np.cos(angle))
            out[:, 1] += mono * gain * float(np.sin(angle))
        echo = self._delay.process(send, self._delay_s)
        out[:, 0] += echo * 0.5
        out[:, 1] += echo * 0.5
        return np.clip(out * self.level, -1.0, 1.0).astype(np.float32)
