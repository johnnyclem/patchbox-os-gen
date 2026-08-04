"""The sample player behind the ``internal`` endpoint.

Speaks the same protocol ``rangerkit.audio.SimpleSynth`` does — ``note_on``,
``note_off``, ``all_off``, ``render``, ``hanging_voices`` — so the shared
``SynthMidiBridge`` drives it unchanged, plus ``control`` for the CC side of
the internal contract (see docs/ARCHITECTURE.md):

* channel = pad index; CC 16/74/10 before a note-on are that hit's
  parameter locks (tune / filter / pan), consumed by the hit; CC 7 is the
  pad's mixer level; channel 15 is the master bus.
* Drum notes are one-shots: a note-off marks the voice released for the
  hanging-voices ledger but lets the sample play out. A *choke* (another pad
  in the same choke group firing) cuts in 5 ms. CC 120/123 cut everything.

Rendering is block-wise numpy with nothing serial per sample: pitch is a
linear-interp read at rate 2^(semis/12), the per-pad tone filter is a small
Hann FIR applied once at trigger (cached per sample × cutoff step), and the
whole voice mix is float32 into the FX bus.
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from rangerkit.audio import BLOCK_FRAMES, SAMPLE_RATE

from core.fxbus import FxBus
from core.kit import Kit
from core.pad import TUNE_RANGE
from core.steps import PADS

log = logging.getLogger("grooveranger.sampler")

MAX_VOICES = 32
CHOKE_FADE = int(SAMPLE_RATE * 0.005)
MASTER_CHANNEL = 15
CC_TUNE, CC_PAN, CC_FILTER = 16, 10, 74
CC_LEVEL, CC_DELAY_DIV, CC_REVERB, CC_DAMP, CC_DUCK = 7, 85, 91, 92, 93
FILTER_STEPS = 16                # cutoff quantization for the FIR cache
_MAX_KERNEL = 64


def load_wav(path: Path) -> np.ndarray:
    """A mono float32 array at SAMPLE_RATE, whatever the file was. Stdlib
    ``wave`` only (16-bit PCM — which is what our kits ship); resampling is
    linear, which is inaudible on drums and keeps soundfile optional."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"{path.name}: only 16-bit PCM kits supported")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(data) > 1:
        positions = np.arange(0, len(data) - 1,
                              rate / SAMPLE_RATE, dtype=np.float64)
        data = np.interp(positions, np.arange(len(data)),
                         data).astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def _tone_kernel(cutoff_step: int) -> np.ndarray | None:
    """A Hann low-pass kernel; None means the filter is open."""
    if cutoff_step >= FILTER_STEPS - 1:
        return None
    closed = 1.0 - cutoff_step / (FILTER_STEPS - 1)
    length = 2 + int(closed * closed * (_MAX_KERNEL - 2))
    kernel = np.hanning(length + 2)[1:-1].astype(np.float32)
    return kernel / kernel.sum()


class SampleBank:
    """Filename -> array cache, plus the filtered variants."""

    def __init__(self) -> None:
        self._raw: dict[str, np.ndarray] = {}
        self._toned: dict[tuple[str, int], np.ndarray] = {}

    def load(self, directory: str, name: str) -> np.ndarray | None:
        key = str(Path(directory) / name)
        if key not in self._raw:
            try:
                self._raw[key] = load_wav(Path(key))
            except (OSError, ValueError, EOFError) as exc:
                log.warning("sample %s unreadable (%s)", name, exc)
                self._raw[key] = np.zeros(1, dtype=np.float32)
        return self._raw[key]

    def toned(self, directory: str, name: str, cutoff: float) -> np.ndarray:
        step = max(0, min(FILTER_STEPS - 1,
                          int(round(cutoff * (FILTER_STEPS - 1)))))
        key = (str(Path(directory) / name), step)
        if key not in self._toned:
            data = self.load(directory, name)
            kernel = _tone_kernel(step)
            self._toned[key] = data if kernel is None else np.convolve(
                data, kernel).astype(np.float32)
        return self._toned[key]


class _Voice:
    __slots__ = ("channel", "note", "data", "position", "rate", "left",
                 "right", "dsend", "rsend", "duck", "released", "fade",
                 "seq")

    def __init__(self, channel, note, data, rate, gain, pan, dsend, rsend,
                 duck, seq) -> None:
        self.channel = channel
        self.note = note
        self.data = data
        self.position = 0.0
        self.rate = rate
        # Equal-power pan.
        angle = (max(-1.0, min(1.0, pan)) + 1.0) * (np.pi / 4)
        self.left = gain * float(np.cos(angle))
        self.right = gain * float(np.sin(angle))
        self.dsend = dsend
        self.rsend = rsend
        self.duck = duck
        self.released = False
        self.fade = -1               # >= 0: samples of choke fade remaining
        self.seq = seq

    def done(self) -> bool:
        return self.position >= len(self.data) - 1 or self.fade == 0

    def take(self, frames: int) -> np.ndarray:
        positions = self.position + self.rate * np.arange(
            frames, dtype=np.float64)
        self.position = float(positions[-1]) + self.rate
        positions = np.clip(positions, 0.0, len(self.data) - 1.001)
        index = positions.astype(np.int64)
        frac = (positions - index).astype(np.float32)
        block = self.data[index] * (1.0 - frac) \
            + self.data[index + 1] * frac
        live = positions < (len(self.data) - 1.01)
        block = np.where(live, block, 0.0).astype(np.float32)
        if self.fade > 0:
            ramp = np.clip(
                np.arange(self.fade, self.fade - frames, -1,
                          dtype=np.float32) / CHOKE_FADE, 0.0, 1.0)
            block *= ramp
            self.fade = max(0, self.fade - frames)
        return block


class Sampler:
    """note_on/note_off/control in (any thread posting through the bridge),
    stereo blocks out (the audio callback)."""

    def __init__(self, kit: Kit | None = None,
                 sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.bank = SampleBank()
        self.fx = FxBus(sample_rate)
        self.kit = Kit()
        self._voices: dict[tuple[int, int], _Voice] = {}
        self._finished: list[_Voice] = []
        self._pending: dict[int, dict[str, float]] = {}
        self._levels = [1.0] * PADS
        self._seq = 0
        if kit is not None:
            self.set_kit(kit)

    # --- kit -----------------------------------------------------------------
    def set_kit(self, kit: Kit) -> None:
        """Swap pad parameters and warm the sample cache. Runs on whatever
        thread the app calls it from — the render thread only ever reads the
        arrays this loads."""
        self.kit = kit.normalised()
        for pad in self.kit.pads:
            for _floor, name in pad.layers:
                self.bank.load(self.kit.directory, name)

    # --- the synth protocol ----------------------------------------------------
    def note_on(self, channel: int, note: int, velocity: int) -> None:
        if not 0 <= channel < PADS:
            return
        pad = self.kit.pads[channel]
        locks = self._pending.pop(channel, {})
        layer = pad.layer_for(velocity)
        if pad.choke:
            # Scan playing-out voices too: a drum's note-off long precedes
            # its natural end, and a choke must cut what is *audible*.
            for voice in list(self._all_voices()):
                other = self.kit.pads[voice.channel] \
                    if voice.channel < PADS else None
                if other is not None and other.choke == pad.choke \
                        and voice.channel != channel and voice.fade < 0:
                    voice.fade = CHOKE_FADE
        if layer is None:
            return                   # sample-less pad: MIDI-only, no voice
        cutoff = locks.get("filter", pad.filter)
        data = self.bank.toned(self.kit.directory, layer, cutoff)
        rate = 2.0 ** (locks.get("tune", pad.tune) / 12.0)
        gain = pad.amp * (velocity / 127.0) * self._levels[channel]
        key = (channel, note)
        held = self._voices.pop(key, None)
        if held is not None:
            held.fade = max(0, min(held.fade if held.fade >= 0
                                   else CHOKE_FADE, CHOKE_FADE))
            self._finished.append(held)
        if len(self._voices) + len(self._finished) >= MAX_VOICES:
            self._steal()
        self._seq += 1
        self._voices[key] = _Voice(
            channel, note, data, rate, gain,
            locks.get("pan", pad.pan), pad.delay_send, pad.reverb_send,
            pad.duck_key, self._seq)

    def note_off(self, channel: int, note: int) -> None:
        voice = self._voices.pop((channel, note), None)
        if voice is not None:
            voice.released = True
            self._finished.append(voice)   # plays out; no longer "hanging"

    def all_off(self, channel: int | None = None) -> None:
        for key in [k for k in self._voices
                    if channel is None or k[0] == channel]:
            voice = self._voices.pop(key)
            voice.released = True
            voice.fade = CHOKE_FADE if voice.fade < 0 else voice.fade
            self._finished.append(voice)

    def control(self, channel: int, number: int, value: int) -> None:
        if channel == MASTER_CHANNEL:
            if number == CC_FILTER:
                self.fx.set_filter(value / 127.0)
            elif number == CC_LEVEL:
                self.fx.set_level(value / 100.0)
            elif number == CC_DELAY_DIV:
                self.fx.set_delay_division(value)
            elif number == CC_REVERB:
                self.fx.set_reverb(value / 127.0)
            elif number == CC_DAMP:
                self.fx.set_damp(value / 127.0)
            elif number == CC_DUCK:
                self.fx.set_duck(value / 127.0)
            return
        if not 0 <= channel < PADS:
            return
        if number == CC_LEVEL:
            self._levels[channel] = min(1.27, value / 100.0)
        elif number == CC_TUNE:
            self._lock(channel, "tune", (value - 64) / 64.0 * TUNE_RANGE)
        elif number == CC_FILTER:
            self._lock(channel, "filter", value / 127.0)
        elif number == CC_PAN:
            self._lock(channel, "pan", (value - 64) / 64.0)

    def _lock(self, channel: int, name: str, value: float) -> None:
        self._pending.setdefault(channel, {})[name] = value

    def set_tempo(self, bpm: float) -> None:
        self.fx.set_tempo(bpm)

    # --- ledgers ---------------------------------------------------------------
    def hanging_voices(self) -> set[tuple[int, int]]:
        """Keyed voices nobody has released — the invariant the engine's
        release book must keep empty, exactly like midi.hanging()."""
        return set(self._voices)

    def sounding(self) -> int:
        return sum(1 for v in self._all_voices() if not v.done())

    def _all_voices(self):
        yield from self._voices.values()
        yield from self._finished

    def _steal(self) -> None:
        victims = sorted(self._all_voices(), key=lambda v: v.seq)
        if not victims:
            return
        victim = victims[0]
        self._voices.pop((victim.channel, victim.note), None)
        if victim in self._finished:
            self._finished.remove(victim)

    # --- rendering -------------------------------------------------------------
    def render(self, frames: int = BLOCK_FRAMES) -> np.ndarray:
        dry = np.zeros((frames, 2), dtype=np.float32)
        dsend = np.zeros(frames, dtype=np.float32)
        rsend = np.zeros(frames, dtype=np.float32)
        key = np.zeros(frames, dtype=np.float32)
        keyed = False
        for voice in list(self._all_voices()):
            if voice.done():
                self._reap(voice)
                continue
            block = voice.take(frames)
            dry[:, 0] += block * voice.left
            dry[:, 1] += block * voice.right
            mono = block * max(voice.left, voice.right)
            if voice.dsend > 0.0:
                dsend += mono * voice.dsend
            if voice.rsend > 0.0:
                rsend += mono * voice.rsend
            if voice.duck:
                key += mono
                keyed = True
            if voice.done():
                self._reap(voice)
        return self.fx.process(dry, dsend, rsend,
                               key=key if keyed else None)

    def _reap(self, voice: _Voice) -> None:
        if voice in self._finished:
            self._finished.remove(voice)
        # A keyed voice that ran out stays keyed until its note-off — the
        # ledger tracks who owes a release, not who is audible.
