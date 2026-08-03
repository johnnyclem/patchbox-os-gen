"""rangerkit.audio — the family's internal sound, honestly sized.

The Pisound DAC can clock 192 kHz; Python synthesis cannot, and pretending
otherwise is how a spec sheet lies. The kit's contract (CONVENTIONS rule 8):
**internal render is 48 kHz float32 stereo in blocks of 256 frames**; the
converter path may run faster, the synthesis does not, and every README that
mentions audio says so.

The pieces:

* ``engine`` — the device layer: a PortAudio (sounddevice) callback when the
  host has one, ``NullAudioOut`` when it does not. Missing package, missing
  device, headless CI — all land on null, and the SET screen says so. The
  exact analogue of ``NullMidiIO``.
* ``synth`` — a small polyphonic table synth (numpy, block-vectorized):
  organ/sine voices with attack/release envelopes, a voice allocator that
  owns every sounding voice, and ``hanging_voices()`` — the audio spelling
  of ``midi.hanging()``.
* ``bridge`` — ``SynthMidiBridge``: a ``MidiIO`` wrapper that peels events
  addressed to the ``internal`` endpoint off to the synth and passes
  everything else through. This is what makes internal audio a *routing
  destination* rather than a new engine concept: any app whose notes can
  reach ``din_out`` can reach the DAC by pointing at ``internal``, and the
  release book releases synth voices exactly the way it releases MIDI notes.
* ``render`` — offline block rendering, no device, deterministic: what CI
  asserts against.

Import discipline: only ``engine`` may import sounddevice (lazily, inside
``open_audio``); ``synth``/``bridge``/``render`` need numpy alone, so the
poisoned-import check keeps passing with no audio stack installed.
"""

SAMPLE_RATE = 48000
BLOCK_FRAMES = 256
CHANNELS = 2

__all__ = ["BLOCK_FRAMES", "CHANNELS", "SAMPLE_RATE", "bridge", "engine",
           "render", "synth"]
