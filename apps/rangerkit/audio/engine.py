"""The device layer — a PortAudio callback, or honest silence.

``open_audio`` is the analogue of ``midi_io.open_midi``: it tries the
configured backend and degrades toward ``NullAudioOut`` rather than
raising. An appliance whose audio stack failed to install boots, draws its
panel, and *says* on the SET screen that audio is null.

sounddevice is imported lazily inside ``open_audio`` — this module must
import cleanly on CI where the package is deliberately absent (it is still
listed in the poisoned-import skip set as belt and braces).

Backend order under "auto": PortAudio picks the host's default device,
which on the appliance is ALSA against the Pisound (and, when the Patchbox
JACK service owns the card, PortAudio's JACK host API). "null" is always
available and always last.
"""
from __future__ import annotations

import logging

from rangerkit.audio import BLOCK_FRAMES, CHANNELS, SAMPLE_RATE

log = logging.getLogger("ranger.audio")

BACKENDS = ("auto", "null")


class NullAudioOut:
    """No device. The renderer is never called; the rig is silent and every
    screen can say so."""

    backend_name = "null"

    def __init__(self, renderer=None) -> None:
        self.renderer = renderer

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        pass


class SoundDeviceOut:              # pragma: no cover - needs a host device
    """The real thing: one PortAudio output stream, the renderer called
    once per block on the callback thread."""

    backend_name = "portaudio"

    def __init__(self, renderer, sample_rate: int = SAMPLE_RATE,
                 block_frames: int = BLOCK_FRAMES, device: str = "") -> None:
        import sounddevice
        self.renderer = renderer
        self._stream = sounddevice.OutputStream(
            samplerate=sample_rate, blocksize=block_frames,
            channels=CHANNELS, dtype="float32",
            device=device or None, callback=self._callback)

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            log.debug("audio callback status: %s", status)
        outdata[:] = self.renderer.render(frames)

    def start(self) -> bool:
        self._stream.start()
        return True

    def stop(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            log.debug("audio stream close failed")


def open_audio(renderer, config=None):
    """Open the configured backend for *renderer*, degrading to null.

    Returns a started ``SoundDeviceOut`` or a ``NullAudioOut`` — callers
    treat both the same and read ``backend_name`` for the panel.
    """
    audio = getattr(config, "audio", None)
    backend = getattr(audio, "backend", "auto")
    if backend == "null":
        return NullAudioOut(renderer)
    try:
        out = SoundDeviceOut(
            renderer,
            sample_rate=int(getattr(audio, "sample_rate", SAMPLE_RATE)),
            block_frames=int(getattr(audio, "block_frames", BLOCK_FRAMES)),
            device=str(getattr(audio, "device", "")))
        out.start()
        log.info("audio: portaudio @ %s Hz",
                 getattr(audio, "sample_rate", SAMPLE_RATE))
        return out
    except Exception as exc:
        log.warning("audio unavailable (%s) — running silent", exc)
        return NullAudioOut(renderer)
