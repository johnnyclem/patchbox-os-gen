"""A small polyphonic table synth — the family's internal voice.

Not SynthRanger (that instrument gets its own engines in Phase 6). This is
the honest minimum that makes ``internal`` a real destination today:
GenRanger's drones, PhraseRanger's slice preview, and the factory patches
those need — sine, a hammond-ish organ stack, and a soft triangle — all
table lookup, all block-vectorized, nothing per-sample in Python.

The invariant mirrors MIDI's: **the allocator owns every sounding voice.**
``note_on`` starts one, ``note_off`` moves it to release, and a voice whose
envelope has died is reaped by ``render``. ``hanging_voices()`` answers the
set still sounding *outside* release — the audio spelling of
``midi.hanging()`` — and every audio test ends by asserting it is empty.

Thread shape: ``note_on``/``note_off`` are called from the engine's tick
thread, ``render`` from the audio callback. State crossing that line is one
dict of slotted voice objects guarded by a mutex held only for bookkeeping —
never during DSP.
"""
from __future__ import annotations

import math
import threading

import numpy as np

from rangerkit.audio import CHANNELS, SAMPLE_RATE

TABLE_SIZE = 2048
MAX_VOICES = 16
ATTACK_S = 0.004
RELEASE_S = 0.120
MASTER_GAIN = 0.5               # headroom before the limiter-less sum

PATCHES = ("sine", "organ", "soft")


def _table(patch: str) -> np.ndarray:
    phase = np.linspace(0.0, 2.0 * math.pi, TABLE_SIZE, endpoint=False)
    if patch == "organ":
        wave = (np.sin(phase) + 0.5 * np.sin(2 * phase)
                + 0.33 * np.sin(3 * phase) + 0.2 * np.sin(4 * phase))
    elif patch == "soft":
        # A rounded triangle: strong fundamental, gentle odd harmonics.
        wave = (np.sin(phase) + 0.15 * np.sin(3 * phase)
                + 0.05 * np.sin(5 * phase))
    else:
        wave = np.sin(phase)
    return (wave / np.max(np.abs(wave))).astype(np.float32)


_TABLES = {name: _table(name) for name in PATCHES}


class _Voice:
    __slots__ = ("note", "phase", "step", "gain", "level", "attack_step",
                 "release_step", "releasing")

    def __init__(self, note: int, velocity: int, sample_rate: int) -> None:
        self.note = note
        frequency = 440.0 * 2.0 ** ((note - 69) / 12.0)
        self.phase = 0.0
        self.step = frequency * TABLE_SIZE / sample_rate
        self.gain = (velocity / 127.0) ** 1.5
        self.level = 0.0
        self.attack_step = 1.0 / max(1, int(ATTACK_S * sample_rate))
        self.release_step = 1.0 / max(1, int(RELEASE_S * sample_rate))
        self.releasing = False


class SimpleSynth:
    """Renderer + allocator. One instance per app, one patch at a time."""

    def __init__(self, patch: str = "organ",
                 sample_rate: int = SAMPLE_RATE,
                 max_voices: int = MAX_VOICES) -> None:
        self.patch = patch if patch in PATCHES else "organ"
        self.sample_rate = sample_rate
        self.max_voices = max_voices
        self._voices: dict[tuple[int, int], _Voice] = {}
        self._lock = threading.Lock()

    # --- the allocator (tick thread) ------------------------------------------
    def note_on(self, channel: int, note: int, velocity: int) -> None:
        with self._lock:
            key = (channel, note)
            if len(self._voices) >= self.max_voices and key not in \
                    self._voices:
                # Steal the quietest voice — the least audible loss.
                victim = min(self._voices,
                             key=lambda k: self._voices[k].level
                             * self._voices[k].gain)
                del self._voices[victim]
            self._voices[key] = _Voice(note, velocity, self.sample_rate)

    def note_off(self, channel: int, note: int) -> None:
        with self._lock:
            voice = self._voices.get((channel, note))
            if voice is not None:
                voice.releasing = True

    def all_off(self, channel: int | None = None) -> None:
        with self._lock:
            for (voice_channel, _note), voice in self._voices.items():
                if channel is None or voice_channel == channel:
                    voice.releasing = True

    def hanging_voices(self) -> set[tuple[int, int]]:
        """Voices sounding and *not* on their way out. The assertion every
        audio test ends with."""
        with self._lock:
            return {key for key, voice in self._voices.items()
                    if not voice.releasing}

    def sounding(self) -> int:
        with self._lock:
            return len(self._voices)

    # --- the renderer (audio callback / offline) ------------------------------
    def render(self, frames: int) -> np.ndarray:
        """One block, float32 (frames, 2). Reaps dead voices. Deterministic:
        same call sequence, same samples."""
        out = np.zeros(frames, dtype=np.float32)
        with self._lock:
            voices = list(self._voices.items())
        dead = []
        table = _TABLES[self.patch]
        for key, voice in voices:
            indices = (voice.phase
                       + voice.step * np.arange(frames)) % TABLE_SIZE
            wave = table[indices.astype(np.int64)]
            envelope = self._envelope(voice, frames)
            out += wave * envelope * (voice.gain * MASTER_GAIN)
            voice.phase = float((voice.phase + voice.step * frames)
                                % TABLE_SIZE)
            if voice.releasing and voice.level <= 0.0:
                dead.append(key)
        if dead:
            with self._lock:
                for key in dead:
                    self._voices.pop(key, None)
        np.clip(out, -1.0, 1.0, out=out)
        return np.repeat(out[:, np.newaxis], CHANNELS, axis=1)

    def _envelope(self, voice: _Voice, frames: int) -> np.ndarray:
        """Linear attack, linear release, block-vectorized with the voice's
        level carried across blocks."""
        if voice.releasing:
            ramp = voice.level - voice.release_step * np.arange(frames)
            voice.level = float(max(0.0, ramp[-1] - voice.release_step))
        else:
            ramp = voice.level + voice.attack_step * np.arange(frames)
            voice.level = float(min(1.0, ramp[-1] + voice.attack_step))
        return np.clip(ramp, 0.0, 1.0).astype(np.float32)
